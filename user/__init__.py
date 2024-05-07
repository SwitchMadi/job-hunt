import uuid

from utilities.sql import get_sql_query_output, execute_sql_query


class User:
    def __init__(self, email=None, name=None):
        self.email = email

        user = User.find_user_by_email(email)
        if user is None:
            self.hash_id = uuid.uuid4()
            self.name = name
            self.save_to_db()
            user = User.find_user_by_email(email)

        self.id = user["id"]
        self.hash_id = user["user_hash_id"]
        self.name = user["name"]

    @staticmethod
    def find_user_by_email(email):
        user_query = f"""
            select *
            from users.users
            where email = '{email}'
        """
        user = get_sql_query_output(user_query)
        if user:
            return user[0]
        else:
            return None

    def save_to_db(self):
        user_create_query = f"""
            insert into users.users
            (user_hash_id, email, name)
            values ('{self.hash_id}', '{self.email}', '{self.name}')
        """
        execute_sql_query(user_create_query)
