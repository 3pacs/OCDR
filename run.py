"""Flask entry point for OCDR web application."""

import sys
from app import create_app

app = create_app()

if __name__ == '__main__':
    frozen = getattr(sys, 'frozen', False)

    print()
    print('=' * 50)
    print('  OCDR Web Application')
    print('=' * 50)
    print()
    print('  Server starting at:  http://localhost:5000')
    print('  Health check:        http://localhost:5000/health')
    print()
    print('  Press Ctrl+C to stop the server.')
    print('=' * 50)
    print()

    app.run(host='0.0.0.0', port=5000, debug=not frozen)
