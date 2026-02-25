from datetime import datetime, timezone
from flask import Blueprint, render_template, request, jsonify
from app import db
from app.models import DevNote

chatbot_bp = Blueprint('chatbot', __name__)


@chatbot_bp.route('/')
def index():
    return render_template('chatbot.html')


@chatbot_bp.route('/api/notes', methods=['GET'])
def list_notes():
    status = request.args.get('status')
    category = request.args.get('category')
    priority = request.args.get('priority')

    query = DevNote.query.order_by(DevNote.created_at.desc())

    if status:
        query = query.filter_by(status=status)
    if category:
        query = query.filter_by(category=category)
    if priority:
        query = query.filter_by(priority=priority)

    notes = query.all()
    return jsonify([_serialize_note(n) for n in notes])


@chatbot_bp.route('/api/notes', methods=['POST'])
def create_note():
    data = request.get_json()
    if not data or not data.get('content', '').strip():
        return jsonify({'error': 'Content is required'}), 400

    note = DevNote(
        content=data['content'].strip(),
        category=data.get('category', 'general').strip().lower(),
        priority=data.get('priority', 'normal').strip().lower(),
        status='open',
        file_path=data.get('file_path', '').strip() or None,
    )
    db.session.add(note)
    db.session.commit()
    return jsonify(_serialize_note(note)), 201


@chatbot_bp.route('/api/notes/<int:note_id>', methods=['PATCH'])
def update_note(note_id):
    note = db.session.get(DevNote, note_id)
    if not note:
        return jsonify({'error': 'Note not found'}), 404

    data = request.get_json()
    if 'status' in data:
        note.status = data['status']
    if 'resolution' in data:
        note.resolution = data['resolution']
    if 'priority' in data:
        note.priority = data['priority']
    if 'category' in data:
        note.category = data['category']
    if 'content' in data:
        note.content = data['content']

    note.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(_serialize_note(note))


@chatbot_bp.route('/api/notes/<int:note_id>', methods=['DELETE'])
def delete_note(note_id):
    note = db.session.get(DevNote, note_id)
    if not note:
        return jsonify({'error': 'Note not found'}), 404

    db.session.delete(note)
    db.session.commit()
    return jsonify({'ok': True})


@chatbot_bp.route('/api/notes/export', methods=['GET'])
def export_notes():
    """Export open notes in a format suitable for Claude Code to process."""
    notes = DevNote.query.filter(
        DevNote.status.in_(['open', 'in_progress'])
    ).order_by(
        db.case(
            (DevNote.priority == 'critical', 0),
            (DevNote.priority == 'high', 1),
            (DevNote.priority == 'normal', 2),
            (DevNote.priority == 'low', 3),
        ),
        DevNote.created_at.asc()
    ).all()

    lines = ['# OCDR Dev Notes - Open Items', '']
    for note in notes:
        lines.append(f'## [{note.category.upper()}] #{note.id} ({note.priority}) - {note.status}')
        lines.append(f'{note.content}')
        if note.file_path:
            lines.append(f'File: {note.file_path}')
        lines.append('')

    return '\n'.join(lines), 200, {'Content-Type': 'text/plain'}


def _serialize_note(note):
    return {
        'id': note.id,
        'content': note.content,
        'category': note.category,
        'status': note.status,
        'priority': note.priority,
        'resolution': note.resolution,
        'file_path': note.file_path,
        'created_at': note.created_at.isoformat() if note.created_at else None,
        'updated_at': note.updated_at.isoformat() if note.updated_at else None,
    }
