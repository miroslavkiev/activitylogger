from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
PIN = "a" * 40


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def test_entitlement_source_has_exact_apple_events_allowlist() -> None:
    entitlements = plistlib.loads(
        (REPO / "ActivityLoggerNative.entitlements").read_bytes()
    )
    assert entitlements == {
        "com.apple.security.automation.apple-events": True,
    }
    for forbidden in (
        "com.apple.security.cs.allow-dyld-environment-variables",
        "com.apple.security.cs.allow-jit",
        "com.apple.security.cs.allow-unsigned-executable-memory",
        "com.apple.security.cs.debugger",
        "com.apple.security.cs.disable-library-validation",
        "com.apple.security.get-task-allow",
    ):
        assert forbidden not in entitlements
    verifier = (REPO / "scripts" / "lib" / "require_certificate_leaf.sh").read_text()
    assert verifier.count('-R="certificate leaf = H\\"$expected\\""') == 2


def _prepare_fake_signer(tmp_path: Path) -> tuple[Path, dict[str, str], Path, list[Path]]:
    repo = tmp_path / "repo with spaces"
    scripts = repo / "scripts"
    libs = scripts / "lib"
    libs.mkdir(parents=True)
    fake_security = tmp_path / "security"
    fake_file = tmp_path / "file"
    fake_codesign = tmp_path / "codesign"

    signer_text = (REPO / "scripts" / "sign_app.sh").read_text(encoding="utf-8")
    signer_text = signer_text.replace("/usr/bin/security", str(fake_security))
    signer_text = signer_text.replace("/usr/bin/file", str(fake_file))
    signer_text = signer_text.replace("/usr/bin/codesign", str(fake_codesign))
    signer = scripts / "sign_app.sh"
    _write_executable(signer, signer_text)
    _write_executable(
        libs / "resolve_repo_root.sh",
        '#!/bin/bash\nresolve_repo_root() { REPO="$ACTIVITYLOGGER_REPO"; export REPO; }\n',
    )
    _write_executable(
        libs / "require_certificate_leaf.sh",
        "#!/bin/bash\n"
        "verify_activitylogger_app() {\n"
        '  printf "verify %s\\n" "$1" >> "$REPO/sign-order"\n'
        "}\n",
    )
    _write_executable(
        fake_security,
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        'if [[ "$1" == "unlock-keychain" ]]; then exit 0; fi\n'
        '[[ "$1" == "find-identity" ]] || exit 2\n'
        'case "${SIGN_IDENTITY_SCENARIO:-one}" in\n'
        f'  one) printf \'  1) {PIN.upper()} "ActivityLogger Code Signing"\\n\' ;;\n'
        f'  duplicate) printf \'  1) {PIN.upper()} "one"\\n  2) {PIN.upper()} "two"\\n\' ;;\n'
        f'  mismatch) printf \'  1) {"b" * 40} "wrong"\\n\' ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
    )
    _write_executable(
        fake_file,
        "#!/bin/bash\n"
        'case "$2" in\n'
        '  *.macho|*/Contents/MacOS/ActivityLoggerNative) printf "Mach-O 64-bit\\n" ;;\n'
        '  *) printf "ASCII text\\n" ;;\n'
        "esac\n",
    )
    _write_executable(
        fake_codesign,
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        'target="${!#}"\n'
        'printf "sign %s\\n" "$target" >> "$ACTIVITYLOGGER_REPO/sign-order"\n',
    )

    app = repo / "dist" / "ActivityLoggerNative.app"
    main = app / "Contents" / "MacOS" / "ActivityLoggerNative"
    framework = app / "Contents" / "Frameworks" / "libpython.macho"
    resource = app / "Contents" / "Resources" / "helper.macho"
    for path in (main, framework, resource):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    (app / "Contents" / "Resources" / "data.txt").write_text(
        "not code", encoding="utf-8"
    )
    identity_dir = repo / ".codesign"
    identity_dir.mkdir()
    (identity_dir / "leaf.sha1").write_text(PIN + "\n", encoding="utf-8")
    (identity_dir / "activitylogger-signing.keychain-db").write_text(
        "fixture", encoding="utf-8"
    )
    (repo / "ActivityLoggerNative.entitlements").write_bytes(
        (REPO / "ActivityLoggerNative.entitlements").read_bytes()
    )
    env = os.environ.copy()
    env["ACTIVITYLOGGER_REPO"] = str(repo)
    return signer, env, app, [framework, resource]


def test_signer_signs_every_nested_macho_before_outer_app(tmp_path: Path) -> None:
    signer, env, app, nested = _prepare_fake_signer(tmp_path)
    result = subprocess.run(
        ["bash", str(signer)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    order = (Path(env["ACTIVITYLOGGER_REPO"]) / "sign-order").read_text().splitlines()
    assert set(order[:-2]) == {f"sign {path}" for path in nested}
    assert order[-2:] == [f"sign {app}", f"verify {app}"]
    assert "--options runtime" not in signer.read_text(encoding="utf-8")


@pytest.mark.parametrize("scenario", ["duplicate", "mismatch"])
def test_signer_rejects_nonunique_or_unpinned_dedicated_identity(
    tmp_path: Path, scenario: str
) -> None:
    signer, env, _, _ = _prepare_fake_signer(tmp_path)
    env["SIGN_IDENTITY_SCENARIO"] = scenario
    result = subprocess.run(
        ["bash", str(signer)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "exactly one valid identity equal to the pinned leaf" in result.stderr
    assert not (Path(env["ACTIVITYLOGGER_REPO"]) / "sign-order").exists()


def _prepare_fake_verifier(tmp_path: Path, scenario: str) -> tuple[Path, Path, dict[str, str]]:
    fake_codesign = tmp_path / "codesign"
    fake_file = tmp_path / "file"
    fake_otool = tmp_path / "otool"
    verifier = tmp_path / "require_certificate_leaf.sh"
    verifier_text = (
        REPO / "scripts" / "lib" / "require_certificate_leaf.sh"
    ).read_text(encoding="utf-8")
    verifier_text = verifier_text.replace("/usr/bin/codesign", str(fake_codesign))
    verifier_text = verifier_text.replace("/usr/bin/file", str(fake_file))
    verifier_text = verifier_text.replace("/usr/bin/otool", str(fake_otool))
    _write_executable(verifier, verifier_text)

    _write_executable(
        fake_codesign,
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        'scenario="${VERIFY_SCENARIO:-ok}"; target="${!#}"; args=" $* "\n'
        'if [[ "$args" == *" --entitlements :- "* ]]; then\n'
        '  if [[ "$scenario" == "legacy-entitlements" ]]; then exit 1; fi\n'
        "  printf '%s' '<?xml version=\"1.0\" encoding=\"UTF-8\"?><plist version=\"1.0\"><dict>'\n"
        "  printf '%s' '<key>com.apple.security.automation.apple-events</key><true/>'\n"
        '  if [[ "$scenario" == "forbidden-entitlement" ]]; then\n'
        "    printf '%s' '<key>com.apple.security.cs.disable-library-validation</key><true/>'\n"
        "  fi\n"
        '  if [[ "$scenario" == "extra-entitlement" ]]; then\n'
        "    printf '%s' '<key>com.example.unapproved</key><true/>'\n"
        "  fi\n"
        "  printf '%s\\n' '</dict></plist>'\n"
        "  exit 0\n"
        "fi\n"
        'if [[ "$args" == *" --verify "* ]]; then\n'
        '  if [[ "$scenario" == "tampered-nested" && "$target" == *.macho ]]; then exit 1; fi\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "$args" == *" -d --verbose=4 "* ]]; then\n'
        '  if [[ -d "$target" ]]; then printf "Identifier=com.mk.activitylogger.native\\n"; fi\n'
        "  printf 'CodeDirectory v=20500 size=1 flags=0x0(none)\\n'\n"
        "  exit 0\n"
        "fi\n"
        'if [[ "$args" == *" -d -r- "* ]]; then\n'
        '  if [[ -d "$target" ]]; then\n'
        f'    printf \'designated => identifier "com.mk.activitylogger.native" and certificate leaf = H"{PIN}"\\n\'\n'
        "  elif [[ \"$scenario\" == \"wrong-nested-leaf\" ]]; then\n"
        f'    printf \'designated => identifier "nested" and certificate leaf = H"{"b" * 40}"\\n\'\n'
        "  else\n"
        f'    printf \'designated => identifier "nested" and certificate leaf = H"{PIN}"\\n\'\n'
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
    )
    _write_executable(
        fake_file,
        "#!/bin/bash\n"
        'case "$2" in\n'
        '  *.macho|*/Contents/MacOS/ActivityLoggerNative) printf "Mach-O 64-bit\\n" ;;\n'
        '  *) printf "ASCII text\\n" ;;\n'
        "esac\n",
    )
    _write_executable(
        fake_otool,
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        'scenario="${VERIFY_SCENARIO:-ok}"; mode="$1"; target="$2"\n'
        'if [[ "$mode" == "-L" ]]; then\n'
        '  printf "%s:\\n" "$target"\n'
        '  if [[ "$scenario" == "external-dependency" && "$target" == *.macho ]]; then\n'
        "    printf '  /tmp/unsigned-plugin.dylib (compatibility version 1.0.0, current version 1.0.0)\\n'\n"
        '  elif [[ "$scenario" == "rpath-traversal" && "$target" == *.macho ]]; then\n'
        "    printf '  @rpath/../../../../../outside.dylib (compatibility version 1.0.0, current version 1.0.0)\\n'\n"
        '  elif [[ "$scenario" == "multiple-rpath-traversal" && "$target" == *.macho ]]; then\n'
        "    printf '  @rpath/../../../peer.dylib (compatibility version 1.0.0, current version 1.0.0)\\n'\n"
        '  elif [[ "$scenario" == "rpath-empty-leading" && "$target" == *.macho ]]; then\n'
        "    printf '  @rpath//peer.dylib (compatibility version 1.0.0, current version 1.0.0)\\n'\n"
        '  elif [[ "$scenario" == "rpath-empty-internal" && "$target" == *.macho ]]; then\n'
        "    printf '  @rpath/peer//child.dylib (compatibility version 1.0.0, current version 1.0.0)\\n'\n"
        '  elif [[ "$scenario" == "rpath-trailing-dot" && "$target" == *.macho ]]; then\n'
        "    printf '  @rpath/peer.dylib/. (compatibility version 1.0.0, current version 1.0.0)\\n'\n"
        '  elif [[ "$scenario" == "valid-bundle-rpath" && "$target" == *.macho ]]; then\n'
        "    printf '  @rpath/peer.dylib (compatibility version 1.0.0, current version 1.0.0)\\n'\n"
        "  else\n"
        "    printf '  /usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)\\n'\n"
        "  fi\n"
        'elif [[ "$mode" == "-l" ]]; then\n'
        '  if [[ "$scenario" == "external-rpath" && "$target" == *.macho ]]; then\n'
        "    printf 'Load command 1\\n          cmd LC_RPATH\\n      cmdsize 40\\n         path /tmp/plugins (offset 12)\\n'\n"
        '  elif [[ ( "$scenario" == "rpath-traversal" || "$scenario" == "valid-bundle-rpath" || "$scenario" == "rpath-empty-leading" || "$scenario" == "rpath-empty-internal" || "$scenario" == "rpath-trailing-dot" ) && "$target" == *.macho ]]; then\n'
        "    printf 'Load command 1\\n          cmd LC_RPATH\\n      cmdsize 40\\n         path @loader_path (offset 12)\\n'\n"
        '  elif [[ "$scenario" == "multiple-rpath-traversal" && "$target" == *.macho ]]; then\n'
        "    printf 'Load command 1\\n          cmd LC_RPATH\\n      cmdsize 40\\n         path @loader_path/safe/deep (offset 12)\\nLoad command 2\\n          cmd LC_RPATH\\n      cmdsize 40\\n         path @executable_path (offset 12)\\n'\n"
        "  fi\n"
        'elif [[ "$mode" == "-D" ]]; then\n'
        '  printf "%s:\\n" "$target"\n'
        "else\n"
        "  exit 2\n"
        "fi\n",
    )

    app = tmp_path / "fixture app" / "ActivityLoggerNative.app"
    main = app / "Contents" / "MacOS" / "ActivityLoggerNative"
    nested = app / "Contents" / "Resources" / "helper.macho"
    for path in (main, nested):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    if scenario == "valid-bundle-rpath":
        (nested.parent / "peer.dylib").write_text("fixture", encoding="utf-8")
    if scenario == "multiple-rpath-traversal":
        (nested.parent / "safe" / "deep").mkdir(parents=True)
    if scenario == "escaping-symlink":
        outside = tmp_path / "outside.dylib"
        outside.write_text("fixture", encoding="utf-8")
        (app / "Contents" / "Resources" / "escape.dylib").symlink_to(outside)
    env = os.environ.copy()
    env["VERIFY_SCENARIO"] = scenario
    return verifier, app, env


def _run_fake_verifier(
    verifier: Path,
    app: Path,
    env: dict[str, str],
    function: str = "verify_activitylogger_app",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; source "$1"; REPO="$2"; '
            f'ACTIVITYLOGGER_CERT_SHA1="$3"; {function} "$4"',
            "bash",
            str(verifier),
            str(app.parents[2]),
            PIN,
            str(app),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_verifier_accepts_exact_nested_signature_and_closed_load_paths(
    tmp_path: Path,
) -> None:
    verifier, app, env = _prepare_fake_verifier(tmp_path, "ok")
    result = _run_fake_verifier(verifier, app, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "certificate_leaf_sha1=" + PIN in result.stdout


def test_verifier_accepts_non_hardened_exact_leaf_bundle(tmp_path: Path) -> None:
    verifier, app, env = _prepare_fake_verifier(tmp_path, "ok")
    result = _run_fake_verifier(verifier, app, env)
    assert result.returncode == 0, result.stdout + result.stderr


def test_rollback_gate_accepts_legacy_profile_but_current_gate_does_not(
    tmp_path: Path,
) -> None:
    verifier, app, env = _prepare_fake_verifier(tmp_path, "legacy-entitlements")
    rollback = _run_fake_verifier(
        verifier, app, env, function="verify_activitylogger_rollback_app"
    )
    current = _run_fake_verifier(verifier, app, env)
    assert rollback.returncode == 0, rollback.stdout + rollback.stderr
    assert current.returncode != 0
    assert "cannot export signed app entitlements" in current.stderr


def test_verifier_accepts_bundle_relative_rpath_target(tmp_path: Path) -> None:
    verifier, app, env = _prepare_fake_verifier(tmp_path, "valid-bundle-rpath")
    result = _run_fake_verifier(verifier, app, env)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("forbidden-entitlement", "forbidden code-signing entitlement"),
        ("extra-entitlement", "must contain exactly one key"),
        ("tampered-nested", "nested Mach-O strict signature verification failed"),
        ("wrong-nested-leaf", "does not use the pinned certificate leaf"),
        ("escaping-symlink", "escaping symlink"),
        ("external-dependency", "non-system, non-bundle dependency"),
        ("external-rpath", "non-system, non-bundle LC_RPATH"),
        ("rpath-traversal", "prohibited traversal components"),
        ("multiple-rpath-traversal", "prohibited traversal components"),
        ("rpath-empty-leading", "empty components"),
        ("rpath-empty-internal", "empty components"),
        ("rpath-trailing-dot", "prohibited traversal components"),
    ],
)
def test_verifier_rejects_broader_entitlements_or_untrusted_nested_code(
    tmp_path: Path, scenario: str, message: str
) -> None:
    verifier, app, env = _prepare_fake_verifier(tmp_path, scenario)
    result = _run_fake_verifier(verifier, app, env)
    assert result.returncode != 0
    assert message in result.stderr
