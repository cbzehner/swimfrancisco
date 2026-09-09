#!/usr/bin/env bash
set -euo pipefail

if ! command -v Xvfb > /dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    xvfb x11vnc novnc websockify openbox dbus-x11 fonts-noto-color-emoji xz-utils
fi
if ! command -v certutil > /dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libnss3-tools
fi
install -d -m 1777 -o root -g root /tmp/.X11-unix

mkdir -p /nix /etc/nix /opt/ms-playwright
chown agent:agent /nix /opt/ms-playwright
cat > /etc/nix/nix.conf <<'EOF'
experimental-features = nix-command flakes
sandbox = false
build-users-group =
extra-substituters = https://devenv.cachix.org https://cachix.cachix.org
extra-trusted-public-keys = devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw= cachix.cachix.org-1:eWNHQldwUO7G2VkjpnjDbWwy4KQ/HNxht7H4SSoMckM=
EOF
if [[ ! -x /home/agent/.nix-profile/bin/nix ]]; then
  curl -fsSL https://releases.nixos.org/nix/nix-2.34.7/install -o /tmp/install-nix
  sudo -H -u agent bash /tmp/install-nix --no-daemon --yes --no-channel-add
fi
if [[ ! -x /home/agent/.nix-profile/bin/devenv ]]; then
  sudo -H -u agent /home/agent/.nix-profile/bin/nix profile add \
    --accept-flake-config github:cachix/devenv/v2.2.2#devenv
fi
for tool in nix nix-store nix-instantiate nix-env devenv; do
  ln -sf "/home/agent/.nix-profile/bin/$tool" "/usr/local/bin/$tool"
done
