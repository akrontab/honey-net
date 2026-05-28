FROM cowrie/cowrie:latest
COPY key_harvester.py /tmp/key_harvester.py
# Append HarvestKeyDB to Cowrie's auth module so auth_class = HarvestKeyDB resolves.
# Exec-form avoids /bin/sh which the Cowrie image does not provide.
RUN ["python3", "-c", "open('/cowrie/cowrie-git/src/cowrie/core/auth.py','a').write(open('/tmp/key_harvester.py').read())"]
