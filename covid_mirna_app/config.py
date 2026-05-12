import os

# 基础配置
SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key'
SQLALCHEMY_TRACK_MODIFICATIONS = False

# 数据库配置
DB_TYPE = os.environ.get('DB_TYPE', 'sqlite')
if DB_TYPE == 'mysql':
    SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://user:password@localhost/covid_mirna_db'
else:
    basedir = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'instance', 'covid_mirna.db')

# 文件上传配置
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB
