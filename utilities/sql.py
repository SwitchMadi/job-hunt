import os
import dotenv
import pandas as pd
import psycopg2
from psycopg2.extras import DictCursor
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from utilities.logging import get_logger


logger = get_logger(name="sql", file_name="job-hunt")


def get_sql_connection(con_type="psycopg2"):
    dotenv.load_dotenv()
    RDS_HOST = os.getenv("RDS_HOST")
    RDS_PORT = os.getenv("RDS_PORT")
    RDS_DB = os.getenv("RDS_DB")
    RDS_USER = os.getenv("RDS_USER")
    RDS_PASSWORD = os.getenv("RDS_PASSWORD")

    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{RDS_USER}:{RDS_PASSWORD}@{RDS_HOST}:{RDS_PORT}/{RDS_DB}"
    )
    if con_type == "psycopg2":
        con = psycopg2.connect(SQLALCHEMY_DATABASE_URI)
    elif con_type == "sqlalchemy":
        engine = create_engine(SQLALCHEMY_DATABASE_URI, poolclass=NullPool)
        con = engine.connect()
    else:
        return None

    return con


def get_sql_query_output(query, con=None, output_as_dataframe=False):
    close_con = False
    if con is None:
        con = get_sql_connection()
        close_con = True

    if output_as_dataframe:
        df = pd.read_sql(query, con)
        if close_con:
            con.close()
        return df
    else:
        cur = con.cursor(cursor_factory=DictCursor)
        cur.execute(query)
        result = cur.fetchall()
        output = []
        for row in result:
            output.append(dict(row))
        if close_con:
            con.close()
        return output


def execute_sql_query(query, con=None):
    close_con = False
    if con is None:
        con = get_sql_connection()
        close_con = True

    try:
        cur = con.cursor()

        if type(query) == tuple:
            query = cur.mogrify(query[0], query[1])

        cur.execute(query)
        con.commit()

        if close_con:
            con.close()

        return True
    except Exception as e:
        if close_con:
            con.close()
        logger.exception(f"Error while executing SQL query - {query}\nError - {e}")
        return False
