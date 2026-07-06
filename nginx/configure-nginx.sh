#!/usr/bin/env bash

. utils.sh

load_module_line=""
if nginx -V 2>&1 | grep -q -- '--with-stream=dynamic'; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get -o Dpkg::Options::="--force-confnew" install -y libnginx-mod-stream
  load_module_line="load_module modules/ngx_stream_module.so;"
fi

backends=""
for _master in $masters; do
  backends="${backends}    server $_master:6443;
"
done
cat <<EOF | tee /tmp/nginx.config.snippet
$load_module_line
stream {
  upstream kube-apiservers {
    $backends
  }
  server {
    listen $lb_port;
    proxy_pass kube-apiservers;
  }
}
EOF

cp nginx/nginx.conf nginx.draft
cat /tmp/nginx.config.snippet >> nginx.draft
if is_address_local $loadbalancer; then
  sudo cp nginx.draft /etc/nginx/nginx.conf
  rm -f nginx.draft
else
  remote_copy nginx.draft $loadbalancer:/etc/nginx/nginx.conf
fi

prnt "Configured nginx on $loadbalancer"
