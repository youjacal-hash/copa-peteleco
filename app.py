import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime
import pytz

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.environ.get('SESSION_SECRET', 'copa-peteleco-2026-secret')

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///copa_peteleco.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

BRASILIA_TZ = pytz.timezone('America/Sao_Paulo')
ADMIN_PASSWORD = 'admin123'

# ─── Modelos do Banco de Dados ────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.String(250), default="")
    avatar_url = db.Column(db.String(500), default="")
    palpites = db.relationship('Palpite', backref='user', lazy=True, cascade="all, delete-orphan")

class Campeonato(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False) # Ex: Brasileirão, Libertadores
    rodadas = db.relationship('Rodada', backref='campeonato', lazy=True, cascade="all, delete-orphan")

class Rodada(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.Integer, nullable=False) # Ex: 19 (para Brasileirão) ou 8 (Oitavas da Liberta)
    campeonato_id = db.Column(db.Integer, db.ForeignKey('campeonato.id'), nullable=False)
    jogos = db.relationship('Jogo', backref='rodada', lazy=True, cascade="all, delete-orphan")

class Jogo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    time_casa = db.Column(db.String(100), nullable=False)
    time_fora = db.Column(db.String(100), nullable=False)
    gols_casa = db.Column(db.Integer, nullable=True)
    gols_fora = db.Column(db.Integer, nullable=True)
    data_hora = db.Column(db.DateTime, nullable=False)
    encerrado = db.Column(db.Boolean, default=False)
    rodada_id = db.Column(db.Integer, db.ForeignKey('rodada.id'), nullable=False)
    palpites = db.relationship('Palpite', backref='jogo', lazy=True, cascade="all, delete-orphan")

class Palpite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    jogo_id = db.Column(db.Integer, db.ForeignKey('jogo.id'), nullable=False)
    palpite_casa = db.Column(db.Integer, nullable=False)
    palpite_fora = db.Column(db.Integer, nullable=False)
    pontos_ganhos = db.Column(db.Integer, default=0)
    data_cadastro = db.Column(db.DateTime, default=lambda: datetime.now(BRASILIA_TZ))

# ─── Helpers ──────────────────────────────────────────────────────────────────

def now_brasilia():
    return datetime.now(BRASILIA_TZ)

def game_is_locked(jogo):
    jogo_dt = BRASILIA_TZ.localize(jogo.data_hora) if jogo.data_hora.tzinfo is None else jogo.data_hora
    return now_brasilia() >= jogo_dt

def calcular_pontos_palpite(p_casa, p_fora, r_casa, r_fora):
    if r_casa is None or r_fora is None:
        return 0
    if p_casa == r_casa and p_fora == r_fora:
        return 3
    if r_casa == r_fora and p_casa == p_fora:
        return 1
    if r_casa > r_fora and p_casa > p_fora:
        return 1
    if r_casa < r_fora and p_casa < p_fora:
        return 1
    return 0

def get_ranking():
    users = User.query.all()
    ranking_data = []
    for u in users:
        total = sum(p.pontos_ganhos for p in u.palpites)
        ranking_data.append({'user': u, 'total_points': total})
    return sorted(ranking_data, key=lambda x: x['total_points'], reverse=True)

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
        return jsonify({'error': 'Não autenticado'}), 401
    
    jogo = Jogo.query.get(game_id)
    if not jogo:
        return jsonify({'error': 'Jogo não encontrado'}), 404
        
    if not game_is_locked(jogo):
        return jsonify({'error': 'Jogo ainda aberto para palpites'}), 403
        
    users = User.query.all()
    result = []
    
    # Mapeia os palpites existentes para este jogo
    pred_map = {p.user_id: p for p in jogo.palpites}
    
    for u in sorted(users, key=lambda x: x.username.lower()):
        p = pred_map.get(u.id)
        result.append({
            'username': u.username,
            'avatar_url': u.avatar_url or '',
            'home_score': p.palpite_casa if p else None,
            'away_score': p.palpite_fora if p else None,
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
        new_bio = request.form.get('bio', '').strip()
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
        user.avatar_url = new_avatar if new_avatar else ""
        user.bio = new_bio
        db.session.commit()
        session['username'] = user.username
        flash('Perfil atualizado com sucesso!', 'success')
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
        jogo_id = request.form.get('game_id', type=int)
        home_score = request.form.get('home_score', type=int)
        away_score = request.form.get('away_score', type=int)

        jogo = Jogo.query.get(jogo_id)
        if jogo and not game_is_locked(jogo) and home_score is not None and away_score is not None:
            pred = Palpite.query.filter_by(user_id=user.id, jogo_id=jogo_id).first()
            if pred:
                pred.palpite_casa = home_score
                pred.palpite_fora = away_score
            else:
                pred = Palpite(user_id=user.id, jogo_id=jogo_id,
                               palpite_casa=home_score, palpite_fora=away_score)
                db.session.add(pred)
            db.session.commit()
            flash('Palpite salvo!', 'success')
        return redirect(url_for('index'))

    # Coleta de jogos filtrados para Brasileirão (Rodada >= 19) e Libertadores
    jogos_brasileirao = Jogo.query.join(Rodada).join(Campeonato)\
        .filter(Campeonato.nome == 'Brasileirão')\
        .filter(Rodada.numero >= 19)\
        .order_by(Rodada.numero, Jogo.data_hora).all()

    jogos_libertadores = Jogo.query.join(Rodada).join(Campeonato)\
        .filter(Campeonato.nome == 'Libertadores')\
        .order_by(Rodada.numero, Jogo.data_hora).all()

    user_preds = {p.jogo_id: p for p in Palpite.query.filter_by(user_id=user.id).all()}

    def enrich_games(games_list):
        enriched = []
        for g in games_list:
            match_dt_brt = BRASILIA_TZ.localize(g.data_hora) if g.data_hora.tzinfo is None else g.data_hora
            enriched.append({
                'game': g,
                'pred': user_preds.get(g.id),
                'locked': game_is_locked(g),
                'match_dt_formatted': match_dt_brt.strftime('%d/%m às %H:%M'),
            })
        return enriched

    ranking = get_ranking()
    return render_template('index.html', user=user, 
                           brasileirao=enrich_games(jogos_brasileirao),
                           libertadores=enrich_games(jogos_libertadores), 
                           ranking=ranking)

# ─── Admin ────────────────────────────────────────────────────────────────────

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    games = Jogo.query.order_by(Jogo.data_hora).all()
    ranking = get_ranking()
    return render_template('admin.html', ranking=ranking, games=games)

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
    jogo_id = request.form.get('game_id', type=int)
    home_score = request.form.get('home_score', type=int)
    away_score = request.form.get('away_score', type=int)
    jogo = Jogo.query.get(jogo_id)
    if jogo and home_score is not None and away_score is not None:
        jogo.gols_casa = home_score
        jogo.gols_fora = away_score
        jogo.encerrado = True
        db.session.commit()
        
        for pred in jogo.palpites:
            pred.pontos_ganhos = calcular_pontos_palpite(pred.palpite_casa, pred.palpite_fora, home_score, away_score)
            
        db.session.commit()
        flash('Resultado salvo e pontos recalculados!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/create_game', methods=['POST'])
def admin_create_game():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    try:
        camp_nome = request.form.get('camp_nome', 'Brasileirão').strip()
        rodada_num = request.form.get('rodada_num', type=int)
        home_team = request.form.get('home_team', '').strip()
        away_team = request.form.get('away_team', '').strip()
        date_str = request.form.get('match_date', '')
        time_str = request.form.get('match_time', '')
        
        dt = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
        
        camp = Campeonato.query.filter_by(nome=camp_nome).first()
        if not camp:
            camp = Campeonato(nome=camp_nome)
            db.session.add(camp)
            db.session.commit()
            
        rodada = Rodada.query.filter_by(numero=rodada_num, campeonato_id=camp.id).first()
        if not rodada:
            rodada = Rodada(numero=rodada_num, campeonato_id=camp.id)
            db.session.add(rodada)
            db.session.commit()

        jogo = Jogo(time_casa=home_team, time_fora=away_team, data_hora=dt, rodada_id=rodada.id)
        db.session.add(jogo)
        db.session.commit()
        flash('Jogo criado com sucesso!', 'success')
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

# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
