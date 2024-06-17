from user import User
import yaml


config = yaml.safe_load(open("config.yml"))

user = User(email=config["user_email"])
user.share_jobs()
