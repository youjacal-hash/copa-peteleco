import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime
import pytz

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.environ.get('SESSION_SECRET', 'copa-peteleco-2026-secret')
# Pega a URL do Neon de forma segura através das configurações do Render
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # Correção necessária: o Render envia 'postgres://', mas o SQLAlchemy exige 'postgresql://'
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///copa_peteleco.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

BRASILIA_TZ = pytz.timezone('America/Sao_Paulo')
ADMIN_PASSWORD = 'admin123'

# ─── Models ───────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    total_points = db.Column(db.Integer, default=0)
    avatar_url = db.Column(db.String(500), nullable=True)
    predictions = db.relationship('Prediction', backref='user', lazy=True, cascade='all, delete-orphan')

class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    stage = db.Column(db.String(50), nullable=False, default='16avos')
    home_team = db.Column(db.String(80), nullable=False)
    away_team = db.Column(db.String(80), nullable=False)
    home_flag = db.Column(db.String(20), nullable=False)
    away_flag = db.Column(db.String(20), nullable=False)
    match_datetime = db.Column(db.DateTime, nullable=False)
    home_score = db.Column(db.Integer, nullable=True)
    away_score = db.Column(db.Integer, nullable=True)
    result_saved = db.Column(db.Boolean, default=False)
    predictions = db.relationship('Prediction', backref='game', lazy=True, cascade='all, delete-orphan')

class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)
    home_score = db.Column(db.Integer, nullable=True)
    away_score = db.Column(db.Integer, nullable=True)
    points = db.Column(db.Integer, default=0)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def now_brasilia():
    return datetime.now(BRASILIA_TZ)

def game_is_locked(game):
    match_dt = BRASILIA_TZ.localize(game.match_datetime) if game.match_datetime.tzinfo is None else game.match_datetime
    return now_brasilia() >= match_dt

def calculate_points(pred_home, pred_away, real_home, real_away):
    if pred_home == real_home and pred_away == real_away:
        return 3
    pred_winner = 'H' if pred_home > pred_away else ('A' if pred_away > pred_home else 'D')
    real_winner = 'H' if real_home > real_away else ('A' if real_away > real_home else 'D')
    if pred_winner == real_winner:
        return 1
    return 0

def get_ranking():
    return User.query.order_by(User.total_points.desc()).all()

def seed_games():
    if Game.query.count() > 0:
        return
    initial_games = [
        ('África do Sul', 'Canadá', 'za', 'ca', datetime(2026, 6, 28, 16, 0)),
        ('Brasil', 'Japão', 'br', 'jp', datetime(2026, 6, 29, 14, 0)),
        ('Alemanha', 'Paraguai', 'de', 'py', datetime(2026, 6, 29, 17, 30)),
        ('Holanda', 'Marrocos', 'nl', 'ma', datetime(2026, 6, 29, 22, 0)),
        ('Costa do Marfim', 'Noruega', 'ci', 'no', datetime(2026, 6, 30, 14, 0)),
        ('França', 'Suécia', 'fr', 'se', datetime(2026, 6, 30, 18, 0)),
        ('México', 'Equador', 'mx', 'ec', datetime(2026, 6, 30, 22, 0)),
        ('Inglaterra', 'RD Congo', 'gb-eng', 'cd', datetime(2026, 7, 1, 13, 0)),
        ('Bélgica', 'Senegal', 'be', 'sn', datetime(2026, 7, 1, 17, 0)),
        ('Estados Unidos', 'Bósnia', 'us', 'ba', datetime(2026, 7, 1, 21, 0)),
        ('Espanha', 'Áustria', 'es', 'at', datetime(2026, 7, 2, 16, 0)),
        ('Portugal', 'Croácia', 'pt', 'hr', datetime(2026, 7, 2, 20, 0)),
        ('Suíça', 'Argélia', 'ch', 'dz', datetime(2026, 7, 3, 0, 0)),
        ('Austrália', 'Egito', 'au', 'eg', datetime(2026, 7, 3, 15, 0)),
        ('Argentina', 'Cabo Verde', 'ar', 'cv', datetime(2026, 7, 3, 19, 0)),
        ('Colômbia', 'Gana', 'co', 'gh', datetime(2026, 7, 3, 22, 30)),
    ]
    for home, away, hf, af, dt in initial_games:
        g = Game(stage='16avos', home_team=home, away_team=away,
                 home_flag=hf, away_flag=af, match_datetime=dt)
        db.session.add(g)
    db.session.commit()

# ─── Auth routes ──────────────────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            flash('Preencha todos os campos.', 'error')
            return render_template('register.html')
        if User.query.filter_by(username=username).first():
            flash('Nome de usuário já em uso.', 'error')
            return render_template('register.html')
        user = User(username=username, password=password)
        db.session.add(user)
        db.session.commit()
        session['user_id'] = user.id
        session['username'] = user.username
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username, password=password).first()
        if not user:
            flash('Usuário ou senha incorretos.', 'error')
            return render_template('login.html')
        session['user_id'] = user.id
        session['username'] = user.username
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/game_predictions/<int:game_id>')
def game_predictions(game_id):
    if 'user_id' not in session:
        return jsonify({'error': 'não autenticado'}), 401
    game = Game.query.get(game_id)
    if not game:
        return jsonify({'error': 'jogo não encontrado'}), 404
    if not game_is_locked(game):
        return jsonify({'error': 'jogo ainda aberto'}), 403
    users = User.query.all()
    result = []
    pred_map = {p.user_id: p for p in game.predictions}
    for u in sorted(users, key=lambda x: x.username.lower()):
        p = pred_map.get(u.id)
        result.append({
            'username': u.username,
            'avatar_url': u.avatar_url or '',
            'home_score': p.home_score if p and p.home_score is not None else None,
            'away_score': p.away_score if p and p.away_score is not None else None,
        })
    return jsonify(result)

@app.route('/perfil', methods=['GET', 'POST'])
def perfil():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))
    if request.method == 'POST':
        new_username = request.form.get('username', '').strip()
        new_password = request.form.get('password', '').strip()
        new_avatar = request.form.get('avatar_url', '').strip()
        if not new_username:
            flash('O nome de usuário não pode ser vazio.', 'error')
            return render_template('perfil.html', user=user)
        existing = User.query.filter_by(username=new_username).first()
        if existing and existing.id != user.id:
            flash('Este nome de usuário já está em uso.', 'error')
            return render_template('perfil.html', user=user)
        user.username = new_username
        if new_password:
            user.password = new_password
        user.avatar_url = new_avatar if new_avatar else None
        db.session.commit()
        session['username'] = user.username
        flash('Perfil updated com sucesso!', 'success')
        return redirect(url_for('perfil'))
    return render_template('perfil.html', user=user)

# ─── Main page ────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))

    if request.method == 'POST':
        game_id = request.form.get('game_id', type=int)
        home_score = request.form.get('home_score', type=int)
        away_score = request.form.get('away_score', type=int)

        game = Game.query.get(game_id)
        if game and not game_is_locked(game) and home_score is not None and away_score is not None:
            pred = Prediction.query.filter_by(user_id=user.id, game_id=game_id).first()
            if pred:
                pred.home_score = home_score
                pred.away_score = away_score
            else:
                pred = Prediction(user_id=user.id, game_id=game_id,
                                  home_score=home_score, away_score=away_score)
                db.session.add(pred)
            db.session.commit()
            flash('Palpite salvo!', 'success')
        return redirect(url_for('index'))

    stages = {
        '16avos': '16-avos de Final',
        'oitavas': 'Oitavas',
        'quartas': 'Quartas',
        'semifinais': 'Semifinais',
        'final': 'Grande Final',
    }

    games_by_stage = {}
    user_preds = {p.game_id: p for p in Prediction.query.filter_by(user_id=user.id).all()}

    for stage_key in stages:
        games = Game.query.filter_by(stage=stage_key).order_by(Game.match_datetime).all()
        games_enriched = []
        for g in games:
            pred = user_preds.get(g.id)
            locked = game_is_locked(g)
            match_dt_brt = BRASILIA_TZ.localize(g.match_datetime) if g.match_datetime.tzinfo is None else g.match_datetime
            games_enriched.append({
                'game': g,
                'pred': pred,
                'locked': locked,
                'match_dt_formatted': match_dt_brt.strftime('%d/%m às %H:%M'),
            })
        games_by_stage[stage_key] = games_enriched

    ranking = get_ranking()
    return render_template('index.html', user=user, stages=stages,
                           games_by_stage=games_by_stage, ranking=ranking)

# ─── Admin ────────────────────────────────────────────────────────────────────

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    users = User.query.order_by(User.total_points.desc()).all()
    stages = {
        '16avos': '16-avos de Final',
        'oitavas': 'Oitavas',
        'quartas': 'Quartas',
        'semifinais': 'Semifinais',
        'final': 'Grande Final',
    }
    games = Game.query.order_by(Game.match_datetime).all()
    return render_template('admin.html', users=users, games=games, stages=stages)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        if pwd == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin'))
        flash('Senha incorreta.', 'error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/save_result', methods=['POST'])
def admin_save_result():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    game_id = request.form.get('game_id', type=int)
    home_score = request.form.get('home_score', type=int)
    away_score = request.form.get('away_score', type=int)
    game = Game.query.get(game_id)
    if game and home_score is not None and away_score is not None:
        game.home_score = home_score
        game.away_score = away_score
        game.result_saved = True
        db.session.commit()
        for pred in game.predictions:
            pts = calculate_points(pred.home_score, pred.away_score, home_score, away_score)
            old_pts = pred.points
            pred.points = pts
            pred.user.total_points += (pts - old_pts)
        db.session.commit()
        flash('Resultado salvo e pontos calculados!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/create_game', methods=['POST'])
def admin_create_game():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    try:
        home_team = request.form.get('home_team', '').strip()
        away_team = request.form.get('away_team', '').strip()
        home_flag = request.form.get('home_flag', '').strip()
        away_flag = request.form.get('away_flag', '').strip()
        stage = request.form.get('stage', '16avos')
        date_str = request.form.get('match_date', '')
        time_str = request.form.get('match_time', '')
        dt = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
        game = Game(stage=stage, home_team=home_team, away_team=away_team,
                    home_flag=home_flag, away_flag=away_flag, match_datetime=dt)
        db.session.add(game)
        db.session.commit()
        flash('Jogo criado!', 'success')
    except Exception as e:
        flash(f'Erro: {e}', 'error')
    return redirect(url_for('admin'))

@app.route('/admin/edit_game', methods=['POST'])
def admin_edit_game():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    try:
        game_id = request.form.get('game_id', type=int)
        game = Game.query.get(game_id)
        if game:
            game.home_team = request.form.get('home_team', game.home_team).strip()
            game.away_team = request.form.get('away_team', game.away_team).strip()
            game.home_flag = request.form.get('home_flag', game.home_flag).strip()
            game.away_flag = request.form.get('away_flag', game.away_flag).strip()
            game.stage = request.form.get('stage', game.stage)
            date_str = request.form.get('match_date', '')
            time_str = request.form.get('match_time', '')
            if date_str and time_str:
                game.match_datetime = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
            db.session.commit()
            flash('Jogo atualizado!', 'success')
    except Exception as e:
        flash(f'Erro: {e}', 'error')
    return redirect(url_for('admin'))

@app.route('/admin/delete_user', methods=['POST'])
def admin_delete_user():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    user_id = request.form.get('user_id', type=int)
    user = User.query.get(user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash('Usuário excluído.', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/update_points', methods=['POST'])
def admin_update_points():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    user_id = request.form.get('user_id', type=int)
    points = request.form.get('points', type=int)
    user = User.query.get(user_id)
    if user and points is not None:
        user.total_points = points
        db.session.commit()
        flash(f'Pontos de {user.username} atualizados para {points}.', 'success')
    return redirect(url_for('admin'))

# ─── Bootstrap & run ─────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    # seed_games()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
