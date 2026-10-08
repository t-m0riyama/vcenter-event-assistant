# 検証専用の OpenLDAP（slapd）。ベース DN は dc=example,dc=org
FROM debian:bookworm-slim
RUN printf '%s\n' \
     'slapd slapd/no_configuration boolean false' \
     'slapd slapd/domain string example.org' \
     'slapd shared/organization string VEA Directory Lab' \
     'slapd slapd/password1 password Lab-Passw0rd!' \
     'slapd slapd/password2 password Lab-Passw0rd!' \
  | debconf-set-selections \
  && apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends slapd ldap-utils ca-certificates \
  && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /entrypoint.sh
COPY ldif/ /ldif/
RUN chmod +x /entrypoint.sh
EXPOSE 389 636
ENTRYPOINT ["/entrypoint.sh"]
