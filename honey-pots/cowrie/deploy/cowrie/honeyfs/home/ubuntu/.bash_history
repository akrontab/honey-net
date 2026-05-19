sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y python3-pip python3-venv git awscli
git clone https://github.com/myorg/backend-api.git
cd backend-api
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
vi .env
python3 manage.py migrate
python3 manage.py runserver 0.0.0.0:8000
sudo systemctl status nginx
sudo systemctl restart nginx
sudo tail -f /var/log/nginx/error.log
aws s3 ls
aws s3 ls s3://myorg-backups/
df -h
free -m
ps aux | grep python
top
w
last
exit
