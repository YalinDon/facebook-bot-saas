<<<<<<< HEAD
# run.py
from app import create_app

app = create_app()

from app import tasks
tasks.init_app(app)

if __name__ == '__main__':
=======
# run.py
from app import create_app

app = create_app()

from app import tasks
tasks.init_app(app)

if __name__ == '__main__':
>>>>>>> fbb69e9e5633005d19d8e9365d836fbf1f87dd2a
    app.run(debug=True, use_reloader=False)