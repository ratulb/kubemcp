#!/usr/bin/env bash
. utils.sh
prnt "Installing kube-apiserver nginx load balancer on $loadbalancer"

install_nginx_from_official_repo() {
  sudo apt update
  sudo apt install -y curl ca-certificates gnupg
  sudo apt autoremove -y

  distro_codename=$(lsb_release -cs)
  case "$distro_codename" in
    bookworm|bullseye)
      repo_type=debian
      nginx_distro=$distro_codename
      ;;
    trixie|sid)
      repo_type=debian
      nginx_distro=bookworm
      ;;
    noble|oracular|plucky)
      repo_type=ubuntu
      nginx_distro=$distro_codename
      ;;
    *)
      repo_type=debian
      nginx_distro=bookworm
      ;;
  esac

  sudo mkdir -p /etc/apt/keyrings
  curl -fsSL https://nginx.org/keys/nginx_signing.key \
    | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/nginx-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/nginx-archive-keyring.gpg] http://nginx.org/packages/$repo_type $nginx_distro nginx" \
    | sudo tee /etc/apt/sources.list.d/nginx.list > /dev/null

  sudo apt update
  sudo DEBIAN_FRONTEND=noninteractive apt-get -o Dpkg::Options::="--force-confnew" install -y nginx
  sudo apt autoremove -y
  prnt "nginx has been installed on $loadbalancer"
}

if is_address_local $loadbalancer; then
  if [ -f /etc/apt/keyrings/nginx-archive-keyring.gpg ] \
     && [ -f /etc/apt/sources.list.d/nginx.list ] \
     && grep -q "nginx.org" /etc/apt/sources.list.d/nginx.list \
     && [ -x /usr/sbin/nginx ]; then
    prnt "nginx (official repo) is already installed"
  else
    install_nginx_from_official_repo
  fi
else
  remote_cmd $loadbalancer bash -s <<'SCRIPT'
    if [ -f /etc/apt/keyrings/nginx-archive-keyring.gpg ] \
       && [ -f /etc/apt/sources.list.d/nginx.list ] \
       && grep -q "nginx.org" /etc/apt/sources.list.d/nginx.list \
       && [ -x /usr/sbin/nginx ]; then
      echo "nginx (official repo) is already installed"
      exit 0
    fi
    distro_codename=$(lsb_release -cs)
    case "$distro_codename" in
      bookworm|bullseye) repo_type=debian; nginx_distro=$distro_codename ;;
      trixie|sid) repo_type=debian; nginx_distro=bookworm ;;
      noble|oracular|plucky) repo_type=ubuntu; nginx_distro=$distro_codename ;;
      *) repo_type=debian; nginx_distro=bookworm ;;
    esac
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://nginx.org/keys/nginx_signing.key \
      | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/nginx-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/nginx-archive-keyring.gpg] http://nginx.org/packages/$repo_type $nginx_distro nginx" \
      | sudo tee /etc/apt/sources.list.d/nginx.list > /dev/null
    sudo apt update
    sudo DEBIAN_FRONTEND=noninteractive apt-get -o Dpkg::Options::="--force-confnew" install -y nginx
    sudo apt autoremove -y
SCRIPT
  prnt "nginx has been installed on $loadbalancer"
fi
