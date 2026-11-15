# Linux service migration handoff

The owner plans to repurpose the existing printer-service laptop and move the
M5C web service and supporting broker to a different Linux host later. This is
planning only; no service migration or printer network cutover has been done.

The current Linux host runs `ankerctl.service`, `m5c-local-dnsmasq.service`,
and `m5c-local-mosquitto.service`. The web service uses the repository checkout,
a separate Python virtual environment, and a private service environment file.
Systemd also defines AP readiness, cloud-mode routing, and local NTP units. The
printer access point has been disabled and the host is connected to its normal
Wi-Fi; active services alone do not establish printer connectivity. Confirm the
printer's actual network and broker connection before relying on this setup.

The owner has a private backup of the service configuration, broker certificate
and key, account configuration, systemd units, and routing helper. Its location
and host-specific details are recorded in the private knowledge system. Do not
commit those files or values to this repository.

Before migration, consult `documentation/INDEX.md`, the Linux installer and
local broker documentation. Inventory the target host's interfaces, network
reachability, printer connection, dependencies, credentials, and existing
services. Choose how the printer will reach the broker and web service; a new
hotspot is a decision, not an assumption. Stage the service and secure private
configuration, verify read-only connectivity and the web interface, and make a
rollback plan before any cutover. Do not move, heat, or operate the printer
without the current-session operator confirmation required by `CLAUDE.md`.
