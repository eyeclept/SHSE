TODO
# Docker things
- Apache Nutch needs to be set up with dockerfile
- make sure everything works on its own
- write tests to check basic functionality on these components
- ensure all containers aren't exposed
# python things
- setup python files
- setup requirements.txt
- setup SHSE_CTL.py which controlls nutch and the CLI
- setup flask web app:
  - use mariadb with sqlalchemy
- make sure it'll work with an external Nutch, Elastic, and MariaDB
# service things
- make it all run as a service with systemd
- set up docker container with networknig for a one system install
- setup docker container with just the SHSE app for use with external containers
- Figure out min reqs
  - note: min requs scale based on parallelization and file type (pdfs are heavy for Tika (in Nutch))