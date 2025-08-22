# run.py
from app import create_app

app = create_app()

from app import tasks
tasks.init_app(app)

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)