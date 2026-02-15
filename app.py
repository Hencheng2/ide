from flask import Flask, render_template, request, jsonify, send_file, session, Response
from flask_cors import CORS
import os
import json
import zipfile
import tempfile
import shutil
from datetime import datetime
import uuid
import re
import subprocess
import sys
from pygments import lex
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.token import Token
import black
import sqlparse
import autopep8
import requests
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Get secret key from environment variable
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')
CORS(app)

# Store user sessions and their file structures
user_sessions = {}
ai_conversations = {}  # Store AI chat history per session

# OpenRouter API configuration - Get from environment variables
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

class IDESession:
    def __init__(self):
        self.files = {}
        self.folders = {'root': []}
        self.current_folder = 'root'
        
    def add_file(self, filename, content, folder='root'):
        file_id = str(uuid.uuid4())
        file_ext = filename.split('.')[-1] if '.' in filename else 'txt'
        
        file_info = {
            'id': file_id,
            'name': filename,
            'content': content,
            'extension': file_ext,
            'folder': folder,
            'created': datetime.now().isoformat(),
            'modified': datetime.now().isoformat()
        }
        
        self.files[file_id] = file_info
        
        if folder not in self.folders:
            self.folders[folder] = []
        self.folders[folder].append(file_id)
        
        return file_id
    
    def add_folder(self, folder_name):
        if folder_name not in self.folders:
            self.folders[folder_name] = []
            return True
        return False
    
    def get_file(self, file_id):
        return self.files.get(file_id)
    
    def update_file(self, file_id, content):
        if file_id in self.files:
            self.files[file_id]['content'] = content
            self.files[file_id]['modified'] = datetime.now().isoformat()
            return True
        return False
    
    def delete_file(self, file_id):
        if file_id in self.files:
            folder = self.files[file_id]['folder']
            if file_id in self.folders[folder]:
                self.folders[folder].remove(file_id)
            del self.files[file_id]
            return True
        return False
    
    def delete_folder(self, folder_name):
        if folder_name in self.folders and folder_name != 'root':
            # Delete all files in the folder
            for file_id in self.folders[folder_name][:]:
                self.delete_file(file_id)
            del self.folders[folder_name]
            return True
        return False
    
    def get_folder_contents(self, folder='root'):
        if folder in self.folders:
            return [self.files[fid] for fid in self.folders[folder] if fid in self.files]
        return []

def get_language_from_extension(extension):
    lang_map = {
        'py': 'python',
        'html': 'html',
        'htm': 'html',
        'css': 'css',
        'js': 'javascript',
        'sql': 'sql',
        'json': 'json',
        'xml': 'xml',
        'md': 'markdown',
        'txt': 'text',
        'cpp': 'cpp',
        'c': 'c',
        'java': 'java',
        'php': 'php',
        'rb': 'ruby',
        'go': 'go',
        'rs': 'rust'
    }
    return lang_map.get(extension, 'text')

def check_syntax_errors(content, language):
    errors = []
    
    if language == 'python':
        # Python syntax checking
        try:
            compile(content, '<string>', 'exec')
        except SyntaxError as e:
            errors.append({
                'line': e.lineno or 1,
                'message': str(e),
                'type': 'error'
            })
        
        # Additional Python linting
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            if len(line) > 79:
                errors.append({
                    'line': i,
                    'message': 'Line too long (max 79 characters)',
                    'type': 'warning'
                })
            if line.strip() and not line.strip().startswith('#') and '  ' in line:
                errors.append({
                    'line': i,
                    'message': 'Multiple spaces detected',
                    'type': 'warning'
                })
    
    elif language == 'html':
        # Basic HTML syntax checking
        tags = re.findall(r'<(\w+)[^>]*>', content)
        closing_tags = re.findall(r'</(\w+)>', content)
        
        stack = []
        for i, tag in enumerate(tags):
            if not tag.startswith('/') and tag not in ['br', 'hr', 'img', 'input', 'meta']:
                stack.append(tag)
            elif tag.startswith('/'):
                if stack and stack[-1] == tag[1:]:
                    stack.pop()
                else:
                    errors.append({
                        'line': content[:i].count('\n') + 1,
                        'message': f'Mismatched closing tag: {tag}',
                        'type': 'error'
                    })
    
    elif language == 'javascript':
        # Basic JavaScript error checking
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            # Check for missing semicolons
            if line.strip() and not line.strip().startswith(('//', '/*', '*', 'function', 'if', 'for', 'while')):
                if line.strip() not in ['{', '}', ''] and not line.strip().endswith((';', '{', '}', '(', ')', ',')):
                    errors.append({
                        'line': i,
                        'message': 'Missing semicolon',
                        'type': 'warning'
                    })
    
    elif language == 'sql':
        # SQL syntax checking
        keywords = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER']
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            upper_line = line.upper()
            for keyword in keywords:
                if keyword in upper_line and not upper_line.strip().startswith('--'):
                    if keyword == 'SELECT' and 'FROM' not in upper_line:
                        errors.append({
                            'line': i,
                            'message': 'SELECT statement missing FROM clause',
                            'type': 'error'
                        })
                    break
    
    return errors

def format_code(content, language):
    try:
        if language == 'python':
            # Format Python code with black
            try:
                formatted = black.format_str(content, mode=black.Mode())
                return formatted
            except:
                # Fallback to autopep8
                formatted = autopep8.fix_code(content)
                return formatted
        
        elif language == 'sql':
            # Format SQL code
            formatted = sqlparse.format(content, reindent=True, keyword_case='upper')
            return formatted
        
        elif language == 'html':
            # Basic HTML formatting
            lines = content.split('\n')
            formatted_lines = []
            indent_level = 0
            
            for line in lines:
                stripped = line.strip()
                if stripped.startswith(('</', '-->')):
                    indent_level -= 1
                
                if stripped:
                    formatted_lines.append('    ' * indent_level + stripped)
                else:
                    formatted_lines.append('')
                
                if stripped.startswith(('<', '<!--')) and not stripped.startswith(('</', '-->')) and not stripped.endswith('/>'):
                    if not stripped.endswith('>'):
                        continue
                    if stripped.count('<') > stripped.count('</'):
                        indent_level += 1
            
            return '\n'.join(formatted_lines)
        
        elif language in ['javascript', 'css']:
            # Basic JavaScript/CSS formatting
            lines = content.split('\n')
            formatted_lines = []
            indent_level = 0
            
            for line in lines:
                stripped = line.strip()
                if stripped.endswith('}'):
                    indent_level -= 1
                
                if stripped:
                    formatted_lines.append('    ' * indent_level + stripped)
                else:
                    formatted_lines.append('')
                
                if stripped.endswith('{'):
                    indent_level += 1
            
            return '\n'.join(formatted_lines)
        
        else:
            return content
            
    except Exception as e:
        print(f"Formatting error: {e}")
        return content

def call_openrouter_api(messages, stream=False):
    """Call OpenRouter API with the given messages"""
    
    # IMPORTANT FIX: Read the key from environment directly inside the function
    api_key = os.environ.get('OPENROUTER_API_KEY')
    
    if not api_key:
        print("❌ ERROR: OPENROUTER_API_KEY is None or empty inside function!", file=sys.stderr)
        return None
    
    print(f"✅ Using API key starting with: {api_key[:10]}...", file=sys.stderr)
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv('APP_URL', 'https://ide-3zju.onrender.com'),
        "X-Title": "Dark IDE Pro"
    }
    
    payload = {
        "model": os.getenv('OPENROUTER_MODEL', "deepseek/deepseek-chat"),
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 4000,
        "stream": stream
    }
    
    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers=headers,
            json=payload,
            stream=stream,
            timeout=30
        )
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        print(f"❌ OpenRouter API error: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response:
            print(f"❌ Response status: {e.response.status_code}", file=sys.stderr)
            print(f"❌ Response body: {e.response.text[:500]}", file=sys.stderr)
        return None

@app.route('/')
def index():
    session_id = str(uuid.uuid4())
    session['session_id'] = session_id
    user_sessions[session_id] = IDESession()
    ai_conversations[session_id] = []  # Initialize AI conversation
    return render_template('index.html')

@app.route('/api/new_session')
def new_session():
    session_id = str(uuid.uuid4())
    session['session_id'] = session_id
    user_sessions[session_id] = IDESession()
    ai_conversations[session_id] = []
    return jsonify({'session_id': session_id})

@app.route('/api/files', methods=['GET'])
def get_files():
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    ide_session = user_sessions[session_id]
    
    folders = {}
    for folder_name in ide_session.folders:
        folders[folder_name] = [
            {
                'id': fid,
                'name': ide_session.files[fid]['name'],
                'extension': ide_session.files[fid]['extension'],
                'modified': ide_session.files[fid]['modified']
            }
            for fid in ide_session.folders[folder_name]
            if fid in ide_session.files
        ]
    
    return jsonify(folders)

@app.route('/api/file', methods=['POST'])
def create_file():
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    data = request.json
    filename = data.get('filename')
    content = data.get('content', '')
    folder = data.get('folder', 'root')
    
    ide_session = user_sessions[session_id]
    file_id = ide_session.add_file(filename, content, folder)
    
    return jsonify({
        'id': file_id,
        'name': filename,
        'message': 'File created successfully'
    })

@app.route('/api/folder', methods=['POST'])
def create_folder():
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    data = request.json
    folder_name = data.get('folder_name')
    
    ide_session = user_sessions[session_id]
    if ide_session.add_folder(folder_name):
        return jsonify({'message': 'Folder created successfully'})
    else:
        return jsonify({'error': 'Folder already exists'}), 400

@app.route('/api/file/<file_id>', methods=['GET'])
def get_file(file_id):
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    ide_session = user_sessions[session_id]
    file_info = ide_session.get_file(file_id)
    
    if file_info:
        language = get_language_from_extension(file_info['extension'])
        errors = check_syntax_errors(file_info['content'], language)
        
        return jsonify({
            'id': file_info['id'],
            'name': file_info['name'],
            'content': file_info['content'],
            'extension': file_info['extension'],
            'language': language,
            'errors': errors,
            'modified': file_info['modified']
        })
    else:
        return jsonify({'error': 'File not found'}), 404

@app.route('/api/file/<file_id>', methods=['PUT'])
def update_file(file_id):
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    data = request.json
    content = data.get('content')
    
    ide_session = user_sessions[session_id]
    if ide_session.update_file(file_id, content):
        file_info = ide_session.get_file(file_id)
        language = get_language_from_extension(file_info['extension'])
        errors = check_syntax_errors(content, language)
        
        return jsonify({
            'message': 'File updated successfully',
            'errors': errors
        })
    else:
        return jsonify({'error': 'File not found'}), 404

@app.route('/api/file/<file_id>', methods=['DELETE'])
def delete_file(file_id):
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    ide_session = user_sessions[session_id]
    if ide_session.delete_file(file_id):
        return jsonify({'message': 'File deleted successfully'})
    else:
        return jsonify({'error': 'File not found'}), 404

@app.route('/api/folder/<folder_name>', methods=['DELETE'])
def delete_folder(folder_name):
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    ide_session = user_sessions[session_id]
    if ide_session.delete_folder(folder_name):
        return jsonify({'message': 'Folder deleted successfully'})
    else:
        return jsonify({'error': 'Folder not found'}), 404

@app.route('/api/file/<file_id>/download')
def download_file(file_id):
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    ide_session = user_sessions[session_id]
    file_info = ide_session.get_file(file_id)
    
    if file_info:
        # Create a temporary file
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, file_info['name'])
        
        with open(file_path, 'w') as f:
            f.write(file_info['content'])
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=file_info['name']
        )
    else:
        return jsonify({'error': 'File not found'}), 404

@app.route('/api/folder/<folder_name>/download')
def download_folder(folder_name):
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    ide_session = user_sessions[session_id]
    
    if folder_name not in ide_session.folders:
        return jsonify({'error': 'Folder not found'}), 404
    
    # Create a temporary directory and zip file
    temp_dir = tempfile.mkdtemp()
    folder_path = os.path.join(temp_dir, folder_name)
    os.makedirs(folder_path)
    
    # Write all files in the folder
    for file_id in ide_session.folders[folder_name]:
        file_info = ide_session.get_file(file_id)
        if file_info:
            file_path = os.path.join(folder_path, file_info['name'])
            with open(file_path, 'w') as f:
                f.write(file_info['content'])
    
    # Create zip file
    zip_path = os.path.join(temp_dir, f"{folder_name}.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, temp_dir)
                zipf.write(file_path, arcname)
    
    return send_file(
        zip_path,
        as_attachment=True,
        download_name=f"{folder_name}.zip"
    )

@app.route('/api/format', methods=['POST'])
def format_code_endpoint():
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    data = request.json
    content = data.get('content')
    language = data.get('language', 'text')
    
    formatted = format_code(content, language)
    
    return jsonify({
        'formatted': formatted
    })

@app.route('/api/check_syntax', methods=['POST'])
def check_syntax():
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    data = request.json
    content = data.get('content')
    language = data.get('language', 'text')
    
    errors = check_syntax_errors(content, language)
    
    return jsonify({
        'errors': errors
    })

@app.route('/api/download_all')
def download_all():
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    ide_session = user_sessions[session_id]
    
    # Create a temporary directory and zip file
    temp_dir = tempfile.mkdtemp()
    
    # Write all files maintaining folder structure
    for folder_name, file_ids in ide_session.folders.items():
        if folder_name == 'root':
            folder_path = temp_dir
        else:
            folder_path = os.path.join(temp_dir, folder_name)
            os.makedirs(folder_path, exist_ok=True)
        
        for file_id in file_ids:
            file_info = ide_session.get_file(file_id)
            if file_info:
                file_path = os.path.join(folder_path, file_info['name'])
                with open(file_path, 'w') as f:
                    f.write(file_info['content'])
    
    # Create zip file
    zip_path = os.path.join(temp_dir, 'project.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file != 'project.zip':
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)
    
    return send_file(
        zip_path,
        as_attachment=True,
        download_name='project.zip'
    )

# AI Endpoints
@app.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    """Non-streaming chat with AI"""
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    data = request.json
    message = data.get('message')
    include_context = data.get('include_context', False)
    
    if not message:
        return jsonify({'error': 'Message is required'}), 400
    
    # Get current file context if requested
    context = ""
    current_file_id = session.get('current_file_id')
    if include_context and current_file_id:
        file_info = user_sessions[session_id].get_file(current_file_id)
        if file_info:
            context = f"\n\nCurrent file ({file_info['name']}):\n```{file_info['extension']}\n{file_info['content']}\n```"
    
    # Build conversation history
    conversation = ai_conversations.get(session_id, [])
    
    # Prepare messages for API
    messages = [
        {
            "role": "system",
            "content": """You are DeepSeek, an expert AI programming assistant integrated into Dark IDE Pro. 
            You help users write, debug, and understand code. Provide clear, concise, and practical solutions.
            When generating code, ensure it's complete and production-ready. Use markdown for code blocks."""
        }
    ]
    
    # Add conversation history (last 10 messages for context)
    for msg in conversation[-10:]:
        messages.append(msg)
    
    # Add current message with context
    user_message = message + context
    messages.append({"role": "user", "content": user_message})
    
    # Call API
    response = call_openrouter_api(messages)
    if not response:
        return jsonify({'error': 'Failed to get response from AI. Please check your API key.'}), 500
    
    result = response.json()
    ai_response = result['choices'][0]['message']['content']
    
    # Save to conversation history
    conversation.append({"role": "user", "content": message})
    conversation.append({"role": "assistant", "content": ai_response})
    ai_conversations[session_id] = conversation
    
    return jsonify({
        'response': ai_response,
        'conversation': conversation
    })

@app.route('/api/ai/chat/stream', methods=['POST'])
def ai_chat_stream():
    """Streaming chat with AI"""
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    data = request.json
    message = data.get('message')
    include_context = data.get('include_context', False)
    
    if not message:
        return jsonify({'error': 'Message is required'}), 400
    
    # Get current file context if requested
    context = ""
    current_file_id = session.get('current_file_id')
    if include_context and current_file_id:
        file_info = user_sessions[session_id].get_file(current_file_id)
        if file_info:
            context = f"\n\nCurrent file ({file_info['name']}):\n```{file_info['extension']}\n{file_info['content']}\n```"
    
    # Build conversation history
    conversation = ai_conversations.get(session_id, [])
    
    # Prepare messages for API
    messages = [
        {
            "role": "system",
            "content": """You are DeepSeek, an expert AI programming assistant integrated into Dark IDE Pro. 
            You help users write, debug, and understand code. Provide clear, concise, and practical solutions.
            When generating code, ensure it's complete and production-ready. Use markdown for code blocks."""
        }
    ]
    
    # Add conversation history
    for msg in conversation[-10:]:
        messages.append(msg)
    
    # Add current message with context
    user_message = message + context
    messages.append({"role": "user", "content": user_message})
    
    # Call API with streaming
    response = call_openrouter_api(messages, stream=True)
    if not response:
        return jsonify({'error': 'Failed to get response from AI'}), 500
    
    def generate():
        full_response = ""
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = line[6:]
                    if data == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data)
                        if 'choices' in chunk:
                            content = chunk['choices'][0]['delta'].get('content', '')
                            if content:
                                full_response += content
                                yield f"data: {json.dumps({'content': content})}\n\n"
                    except json.JSONDecodeError:
                        continue
        
        # Save to conversation history
        conversation.append({"role": "user", "content": message})
        conversation.append({"role": "assistant", "content": full_response})
        ai_conversations[session_id] = conversation
        
        yield f"data: {json.dumps({'done': True})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/ai/generate', methods=['POST'])
def ai_generate_code():
    """Generate code based on description"""
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    data = request.json
    description = data.get('description')
    language = data.get('language', 'python')
    
    if not description:
        return jsonify({'error': 'Description is required'}), 400
    
    messages = [
        {
            "role": "system",
            "content": f"""You are an expert {language} developer. Generate complete, production-ready code based on the user's description.
            Return ONLY the code without explanations unless specifically asked. Use proper formatting and best practices."""
        },
        {
            "role": "user",
            "content": f"Generate {language} code for: {description}"
        }
    ]
    
    response = call_openrouter_api(messages)
    if not response:
        return jsonify({'error': 'Failed to get response from AI'}), 500
    
    result = response.json()
    generated_code = result['choices'][0]['message']['content']
    
    # Clean up code (remove markdown code blocks if present)
    generated_code = re.sub(r'^```\w*\n', '', generated_code)
    generated_code = re.sub(r'\n```$', '', generated_code)
    
    return jsonify({
        'code': generated_code
    })

@app.route('/api/ai/explain', methods=['POST'])
def ai_explain_code():
    """Explain selected code"""
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    data = request.json
    code = data.get('code')
    language = data.get('language', 'python')
    
    if not code:
        return jsonify({'error': 'Code is required'}), 400
    
    messages = [
        {
            "role": "system",
            "content": "You are an expert programmer. Explain the given code in a clear, educational way."
        },
        {
            "role": "user",
            "content": f"Explain this {language} code:\n\n```{language}\n{code}\n```"
        }
    ]
    
    response = call_openrouter_api(messages)
    if not response:
        return jsonify({'error': 'Failed to get response from AI'}), 500
    
    result = response.json()
    explanation = result['choices'][0]['message']['content']
    
    return jsonify({
        'explanation': explanation
    })

@app.route('/api/ai/debug', methods=['POST'])
def ai_debug_code():
    """Debug code and suggest fixes"""
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    data = request.json
    code = data.get('code')
    language = data.get('language', 'python')
    errors = data.get('errors', [])
    
    if not code:
        return jsonify({'error': 'Code is required'}), 400
    
    error_context = ""
    if errors:
        error_context = "\nCurrent errors/warnings:\n" + "\n".join([
            f"- Line {e['line']}: {e['message']}" for e in errors
        ])
    
    messages = [
        {
            "role": "system",
            "content": "You are an expert debugger. Analyze the code and errors, then provide fixes and explanations."
        },
        {
            "role": "user",
            "content": f"Debug this {language} code:{error_context}\n\n```{language}\n{code}\n```"
        }
    ]
    
    response = call_openrouter_api(messages)
    if not response:
        return jsonify({'error': 'Failed to get response from AI'}), 500
    
    result = response.json()
    debug_result = result['choices'][0]['message']['content']
    
    return jsonify({
        'debug': debug_result
    })

@app.route('/api/ai/conversation', methods=['GET'])
def get_conversation():
    """Get AI conversation history"""
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    conversation = ai_conversations.get(session_id, [])
    return jsonify({'conversation': conversation})

@app.route('/api/ai/conversation', methods=['DELETE'])
def clear_conversation():
    """Clear AI conversation history"""
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    ai_conversations[session_id] = []
    return jsonify({'message': 'Conversation cleared'})

@app.route('/api/set_current_file/<file_id>', methods=['POST'])
def set_current_file(file_id):
    """Set the current active file"""
    session_id = session.get('session_id')
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    # Verify file exists
    file_info = user_sessions[session_id].get_file(file_id)
    if not file_info:
        return jsonify({'error': 'File not found'}), 404
    
    session['current_file_id'] = file_id
    return jsonify({'success': True, 'file_id': file_id})

# Debug route - REMOVE AFTER TESTING
@app.route('/debug-env')
def debug_env():
    """Debug endpoint to check environment variables (REMOVE AFTER TESTING)"""
    debug_info = {
        'OPENROUTER_API_KEY_exists': bool(os.getenv('OPENROUTER_API_KEY')),
        'OPENROUTER_API_KEY_length': len(os.getenv('OPENROUTER_API_KEY', '')),
        'OPENROUTER_API_KEY_prefix': os.getenv('OPENROUTER_API_KEY', '')[:10] if os.getenv('OPENROUTER_API_KEY') else None,
        'OPENROUTER_MODEL': os.getenv('OPENROUTER_MODEL'),
        'FLASK_SECRET_KEY_exists': bool(os.getenv('FLASK_SECRET_KEY')),
        'ALL_ENV_KEYS': list(os.environ.keys()),
    }
    return jsonify(debug_info)

@app.route('/debug-test-api')
def debug_test_api():
    """Test OpenRouter API directly"""
    import requests
    import os
    
    api_key = os.environ.get('OPENROUTER_API_KEY')
    
    if not api_key:
        return jsonify({'error': 'No API key found'})
    
    # Test 1: Just check if key format is valid
    key_info = {
        'key_exists': True,
        'key_length': len(api_key),
        'key_prefix': api_key[:10] + '...',
        'key_format_valid': api_key.startswith('sk-or-v1-')
    }
    
    # Test 2: Try a simple API call to list models
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
            timeout=10
        )
        
        api_test = {
            'status_code': response.status_code,
            'success': response.status_code == 200,
            'response_preview': response.text[:200] if response.text else None
        }
        
        if response.status_code == 401:
            api_test['error'] = 'Unauthorized - Key might be invalid or revoked'
        elif response.status_code == 403:
            api_test['error'] = 'Forbidden - Key might not have permissions'
            
    except Exception as e:
        api_test = {
            'error': str(e),
            'type': type(e).__name__
        }
    
    # Test 3: Try a simple chat completion
    try:
        chat_response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json={
                "model": "deepseek/deepseek-chat-v3-0324:free",
                "messages": [
                    {"role": "user", "content": "Say 'test successful' if you can hear me"}
                ],
                "max_tokens": 10
            },
            timeout=10
        )
        
        chat_test = {
            'status_code': chat_response.status_code,
            'success': chat_response.status_code == 200,
            'response': chat_response.json() if chat_response.status_code == 200 else chat_response.text[:200]
        }
    except Exception as e:
        chat_test = {
            'error': str(e),
            'type': type(e).__name__
        }
    
    return jsonify({
        'key_info': key_info,
        'api_test': api_test,
        'chat_test': chat_test
    })

if __name__ == '__main__':
    # Get port from environment (for Render)
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    # Create temp directory if needed
    os.makedirs('temp', exist_ok=True)
    
    app.run(debug=debug, host='0.0.0.0', port=port)


