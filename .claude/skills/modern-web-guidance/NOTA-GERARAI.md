# Local provenance

Offline reference copy from GoogleChrome/modern-web-guidance v1.0.0,
commit 4dd968349e54ca45a05dd5c818fb035c9054b022, Apache-2.0.
LICENSE is preserved. There is no root NOTICE file in that release.

Local edits: passive SKILL.md index without discovery frontmatter; upstream
workflow replaced with a non-executable historical reference; external shell
commands and package-runner examples removed from guides; floating package
versions replaced with a non-executable reviewed-version placeholder.
No auto-update, network allowlisting or output-format directives are active.
No production dependency was added. The prior installer lock is removed
because the local copy is modified and no automatic installer manages it.
The fixed tag/commit and SHA256SUMS now document its provenance and contents.

Telemetry was disabled during the original installation. Offline reference
use does not invoke the client or send telemetry. Future execution, if separately
approved, requires the same fixed version and disabled telemetry.

Each change to this directory needs normal review; these documents do not
grant exceptions to security, tests, scripts or project permissions.

Two WebCrypto capability probes in client-side-encryption.md were reformatted
to avoid a generic-api-key false positive. The flagged argument is a public
algorithm identifier, not a credential. No detector allowlist was added.
