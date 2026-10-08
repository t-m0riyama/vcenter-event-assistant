# 検証専用の Samba AD DC（arm64 / amd64 のどちらでも動くよう Debian から作る）
FROM debian:bookworm-slim
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
     samba samba-ad-dc samba-ad-provision winbind krb5-user ldap-utils ca-certificates \
  && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /entrypoint.sh
COPY seed.ldif /seed.ldif
RUN chmod +x /entrypoint.sh
EXPOSE 389 636
ENTRYPOINT ["/entrypoint.sh"]
