"""WSGI entrypoint for production servers (gunicorn etc.)."""

from app import create_app


app = create_app()


if __name__ == '__main__':
    import os

    debug = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 'yes')
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=debug, host='0.0.0.0', port=port)
