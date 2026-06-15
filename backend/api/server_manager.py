from pydantic import BaseModel
import docker
from docker.errors import NotFound
import os
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from sqlmodel import Field, Session, SQLModel, create_engine, select, or_
import uuid
from enum import Enum

# Asegurate de que esta función exista en tu rcon_manager
from rcon_manager import execute_rcon_command
ADMIN_SECRET = "changeme"  # Cambia esto por un secreto real en producción
app = FastAPI(title="CS2 Orchestrator API")
# =========================================================================
# Funciones internas (port and api key provisioning)
# =========================================================================

def seed_port_pool():
    """
    Se ejecuta al arrancar el backend. Si la base de datos es nueva,
    crea el inventario de puertos permitidos para el servidor.
    """
    with Session(engine) as session:
        # Chequeamos si ya existen puertos cargados
        puertos_existentes = session.exec(select(PortPool)).first()
        
        if not puertos_existentes:
            print("📦 [PortPool] Base de datos limpia detectada. Cargando inventario de puertos...")
            
            RANGO_INICIO = 27100
            CANTIDAD_MAXIMA_SERVIDORES = 50  # Levantamos hasta 50 servidores en simultáneo
            
            for i in range(CANTIDAD_MAXIMA_SERVIDORES):
                game_p = RANGO_INICIO + (i * 3)
                tv_p = game_p + 1
                rcon_p = game_p + 2
                
                nuevo_bloque = PortPool(
                    game_port=game_p,
                    tv_port=tv_p,
                    rcon_port=rcon_p,
                    in_use=False
                )
                session.add(nuevo_bloque)
            
            session.commit()
            print(f"✅ [PortPool] {CANTIDAD_MAXIMA_SERVIDORES} bloques de puertos listos para usar.")
        else:
            print("📦 [PortPool] Inventario de puertos verificado (ya existían datos).")

def get_free_ports(session_id:str):
    with Session(engine) as session:
        free_port = session.exec(select(PortPool).where(PortPool.in_use == False)).first()
        if not free_port:
            raise HTTPException(status_code=500, detail="No hay suficientes puertos libres disponibles")
        # Marcar los puertos como usados
        free_port.in_use = True
        free_port.assigned_session_id = session_id
        game_port = free_port.game_port
        session.add(free_port)
        session.commit()
        
        return game_port

def release_ports(session_id:str):
    with Session(engine) as session:
        port = session.exec(select(PortPool).where(PortPool.assigned_session_id == session_id)).first()
        if not port:
            raise HTTPException(status_code=500, detail="No hay suficientes puertos libres disponibles")
        # Marcar los puertos como no usados
        port.in_use = False
        port.assigned_session_id = None
        session.add(port)
        session.commit()
        
        return 1

def reserve_ports(session_id:str, game_port:int):
    with Session(engine) as session:
        port = session.exec(select(PortPool).where(PortPool.game_port == game_port)).first()
        if not port:
            raise HTTPException(status_code=404, detail="El puerto solicitado no existe en el inventario")
        if port.in_use:
            raise HTTPException(status_code=500, detail="El puerto solicitado ya está en uso")
        # Marcar los puertos como usados
        port.in_use = True
        port.assigned_session_id = session_id
        port.game_port = game_port
        port.tv_port = game_port + 1
        port.rcon_port = game_port + 2
        session.add(port)
        session.commit()
        
        return 1

def get_free_token(session_id:str):
    with Session(engine) as session:
        free_token = session.exec(select(SRCDSPool).where(SRCDSPool.in_use == False)).first()
        if not free_token:
            raise HTTPException(status_code=500, detail="No hay suficientes tokens libres disponibles")
        # Marcar los tokens como usados
        free_token.in_use = True
        free_token.assigned_session_id = session_id
        token = free_token.token
        session.add(free_token)
        session.commit()
        
        return token

def reserve_token(session_id:str, token:str):
    with Session(engine) as session:
        token_entry = session.exec(select(SRCDSPool).where(SRCDSPool.token == token)).first()
        if not token_entry:
            return 1
        if token_entry.in_use:
            raise HTTPException(status_code=500, detail="El token solicitado ya está en uso")
        # Marcar los tokens como usados
        token_entry.in_use = True
        token_entry.assigned_session_id = session_id
        session.add(token_entry)
        session.commit()
        
        return 1

def release_token(session_id:str):
    with Session(engine) as session:
        token = session.exec(select(SRCDSPool).where(SRCDSPool.assigned_session_id == session_id)).first()
        if not token:
            raise HTTPException(status_code=500, detail="No hay suficientes tokens libres disponibles")
        # Marcar los tokens como no usados
        token.in_use = False
        token.assigned_session_id = None
        session.add(token)
        session.commit()
        
        return token
# =========================================================================
# SEPARACIÓN DE MODELOS (Esquemas de Entrada vs Tabla de DB)
# =========================================================================
class statuses(str, Enum):
    creating = "creating"
    online = "online"
    stopping = "stopping"
    destroyed = "destroyed"
    error = "error"
    
class MatchBase(SQLModel):
    server_name: str

class MatchCreate(MatchBase):
    srcds_token: str
    game_port: int

class Match(MatchBase, table=True):
    """Tabla real en SQLite con todos los detalles de infraestructura"""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    
    srcds_token: Optional[str] = None
    game_port: Optional[int] = None
    tv_port: Optional[int] = None
    rcon_port: Optional[int] = None
    
    container_id: Optional[str] = None
    status: statuses = Field(default=statuses.creating)
    jugadores_actuales: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    destroyed_at: str = ""

class PortPool(SQLModel, table=True):
    """inventario de puertos disponibles para asignar a los servidores"""
    game_port: int = Field(primary_key=True)
    assigned_session_id: Optional[str] = Field(default=None, unique=True)
    tv_port: int
    rcon_port: int
    in_use: bool = Field(default=False)

class SRCDSPool(SQLModel, table=True):
    """inventario de tokens SRCDS disponibles para asignar a los servidores"""
    token: str = Field(primary_key=True, unique=True)
    assigned_session_id: Optional[str] = Field(default=None, unique=True)
    in_use: bool = Field(default=False)
    
# Conexión automática a SQLite
DB_FILE = "servers.db"
engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})

# Crea las tablas al arrancar
SQLModel.metadata.create_all(engine)

seed_port_pool()

try:
    docker_client = docker.from_env()
except Exception as e:
    print(f"Error al conectar con Docker daemon: {e}")
    exit(1)


# =========================================================================
# RUTAS DE LA API
# =========================================================================

@app.post("/matches/launch")
def api_launch_server(config: MatchCreate):
    session_id = str(uuid.uuid4())
    
    reserve_ports(session_id, config.game_port)
    reserve_token(session_id, config.srcds_token)
    
    # 1. Guardar registro inicial en la DB y generar el UUID automático
    with Session(engine) as session:
        # Validamos y volcamos los datos de MatchCreate hacia el Match de la DB
        nuevo_match = Match.model_validate(config)
        nuevo_match.session_id = session_id
        game_port = config.game_port
        nuevo_match.tv_port = game_port + 1
        nuevo_match.rcon_port = game_port + 2
        session.add(nuevo_match)
        session.commit()
        session.refresh(nuevo_match)
        
        # Guardamos el session_id generado para usarlo en Docker y logs
        session_id = nuevo_match.session_id

    # 2. Calcular rutas absolutas del host
    actual_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.abspath(os.path.join(actual_dir, "../../cs2-server-base"))
    
    steamcmd_cache = f"{base_dir}/steamcmd-cache"
    steam_cache = f"{base_dir}/steam-cache"
    
    os.makedirs(steamcmd_cache, exist_ok=True)
    os.makedirs(steam_cache, exist_ok=True)

    print(f"[Match-{session_id}] Preparando contenedor en Python...")

    try:
        # 3. Lanzar el contenedor Docker
        container = docker_client.containers.run(
            image='joedwards32/cs2',
            name=f"cs2-match-{session_id}",
            detach=True,
            stdin_open=True,
            tty=True,
            environment={
                "session_id": session_id,
                "SRCDS_TOKEN": nuevo_match.srcds_token,
                "CS2_SERVERNAME": nuevo_match.server_name,
                "GAME_PORT": "27015",
                "TV_PORT": "27020",
                "CS2_RCON_PORT": "27017",
                "DEBUG": "3",
                "STEAMAPPVALIDATE": "0",
                "CS2_CHEATS": "1",
                "CS2_SERVER_HIBERNATE": "0",
                "CS2_LAN": "0",
                "CS2_RCONPW": "changeme",
                "CS2_MAXPLAYERS": "10",
                "CS2_STARTMAP": "de_inferno",
                "CS2_LOG": "on"
            },
            volumes={
                base_dir: {'bind': '/home/steam/cs2-dedicated/', 'mode': 'ro'},
                steamcmd_cache: {'bind': '/home/steam/steamcmd', 'mode': 'rw'},
                steam_cache: {'bind': '/home/steam/Steam', 'mode': 'rw'}
            },
            ports={
                '27015/tcp': nuevo_match.game_port,
                '27015/udp': nuevo_match.game_port,
                '27020/udp': nuevo_match.tv_port,
                '27017/tcp': nuevo_match.rcon_port
            }
        )

        # 4. Actualizar el estado a 'online' abriendo una sesión válida
        with Session(engine) as session:
            db_match = session.get(Match, session_id)
            if db_match:
                db_match.status = statuses.online
                db_match.container_id = container.short_id
                db_match.created_at = datetime.now().isoformat()
                session.add(db_match)
                session.commit()

        print(f"[Match-{session_id}] ¡Servidor levantado con éxito!")
        return {
            "status": "success",
            "message": f"Servidor para match {session_id} lanzado",
            "session_id": session_id,
            "container_id": container.short_id,
            "puerto": config.game_port
        }

    except Exception as e:
        # Si Docker falla, registramos el error en este match
        with Session(engine) as session:
            db_match = session.get(Match, session_id)
            if db_match:
                db_match.status = statuses.error
                session.add(db_match)
                session.commit()
        raise HTTPException(status_code=500, detail=f"Error al crear contenedor: {str(e)}")

@app.post("/matches/autolaunch")
def api_autolaunch_server(config: MatchBase):
    
    # 1. Guardar registro inicial en la DB y generar el UUID automático
    with Session(engine) as session:
        
        # Generamos el UUID acá arriba en Python explícitamente para tenerlo disponible
        session_id = str(uuid.uuid4())
        
        # 2. Buscamos y reservamos los recursos pasando la 'session' activa
        game_port = get_free_ports(session_id)
        srcds_token = get_free_token(session_id)
        
        # 3. Validamos y volcamos los datos básicos del Request (server_name)
        nuevo_match = Match.model_validate(config)
        
        # 4. Inyectamos los datos calculados e internos al objeto de la DB
        nuevo_match.session_id = session_id
        nuevo_match.srcds_token = srcds_token
        nuevo_match.game_port = game_port
        nuevo_match.tv_port = game_port + 1
        nuevo_match.rcon_port = game_port + 2
        nuevo_match.status = statuses.creating # Estado inicial seguro
        
        # 5. Guardamos TODO junto en un solo bloque atómico
        session.add(nuevo_match)
        session.commit() # Al hacer commit, se guardan los puertos, el token y el match a la vez
        session.refresh(nuevo_match)
        
    # 2. Calcular rutas absolutas del host
    actual_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.abspath(os.path.join(actual_dir, "../../cs2-server-base"))
    
    steamcmd_cache = f"{base_dir}/steamcmd-cache"
    steam_cache = f"{base_dir}/steam-cache"
    
    os.makedirs(steamcmd_cache, exist_ok=True)
    os.makedirs(steam_cache, exist_ok=True)

    print(f"[Match-{session_id}] Preparando contenedor en Python...")

    try:
        # 3. Lanzar el contenedor Docker
        container = docker_client.containers.run(
            image='joedwards32/cs2',
            name=f"cs2-match-{session_id}",
            detach=True,
            stdin_open=True,
            tty=True,
            environment={
                "session_id": session_id,
                "SRCDS_TOKEN": nuevo_match.srcds_token,
                "CS2_SERVERNAME": nuevo_match.server_name,
                "GAME_PORT": "27015",
                "TV_PORT": "27020",
                "CS2_RCON_PORT": "27017",
                "DEBUG": "3",
                "STEAMAPPVALIDATE": "0",
                "CS2_CHEATS": "1",
                "CS2_SERVER_HIBERNATE": "0",
                "CS2_LAN": "0",
                "CS2_RCONPW": "changeme",
                "CS2_MAXPLAYERS": "10",
                "CS2_STARTMAP": "de_inferno",
                "CS2_LOG": "on"
            },
            volumes={
                base_dir: {'bind': '/home/steam/cs2-dedicated/', 'mode': 'rw'},
                steamcmd_cache: {'bind': '/home/steam/steamcmd', 'mode': 'rw'},
                steam_cache: {'bind': '/home/steam/Steam', 'mode': 'rw'}
            },
            ports={
                '27015/tcp': nuevo_match.game_port,
                '27015/udp': nuevo_match.game_port,
                '27020/udp': nuevo_match.tv_port,
                '27017/tcp': nuevo_match.rcon_port
            }
        )

        # 4. Actualizar el estado a 'online' abriendo una sesión válida
        with Session(engine) as session:
            db_match = session.get(Match, session_id)
            if db_match:
                db_match.status = statuses.online
                db_match.container_id = container.short_id
                db_match.created_at = datetime.now().isoformat()
                session.add(db_match)
                session.commit()

        print(f"[Match-{session_id}] ¡Servidor levantado con éxito!")
        return {
            "status": "success",
            "message": f"Servidor para match {session_id} lanzado",
            "session_id": session_id,
            "container_id": container.short_id,
            "puerto": game_port
        }

    except Exception as e:
        # Si Docker falla, registramos el error en este match
        with Session(engine) as session:
            db_match = session.get(Match, session_id)
            if db_match:
                db_match.status = statuses.error
                session.add(db_match)
                session.commit()
        raise HTTPException(status_code=500, detail=f"Error al crear contenedor: {str(e)}")

@app.get("/matches")
def api_listar_matches(status: Optional[statuses] = None):
    with Session(engine) as session:
        query = select(Match)
        if status is not None:
            query = query.where(Match.status == status)
        partidas = session.exec(query).all()
        return partidas

@app.post("/matches/destroy")
def api_destroy_server(session_id: str):
    try:
        container_name = f"cs2-match-{session_id}"
        container = docker_client.containers.get(container_name)
        current_session_id = None
        
        # Actualizamos estado a "stopping"
        with Session(engine) as session_db:
            db_match = session_db.get(Match, session_id)
            if db_match:
                db_match.status = statuses.stopping
                session_db.add(db_match)
                session_db.commit()

        print(f"[Docker] Deteniendo {container_name}...")
        container.stop(timeout=10)
        
        print(f"[Docker] Eliminando {container_name}...")
        container.remove()
        
        # Actualizamos estado final a "destroyed"
        with Session(engine) as session_db:
            release_ports(session_id)
            release_token(session_id)
            db_match = session_db.get(Match, session_id)
            if db_match:
                current_session_id = db_match.session_id
                db_match.status = statuses.destroyed
                db_match.destroyed_at = datetime.now().isoformat()
                session_db.add(db_match)
                session_db.commit()

        return {
            "status": "success",
            "message": f"Servidor para match {session_id} destruido",
            "session_id": current_session_id,
            "container_id": container.short_id,
        }
    except NotFound:
        raise HTTPException(status_code=404, detail=f"No se encontró un servidor para sesión {session_id}")        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al destruir contenedor: {str(e)}")

@app.get("/matches/get_server_status")
def api_get_server_status(session_id: str):
    try:
        container_name = f"cs2-match-{session_id}"
        container = docker_client.containers.get(container_name)
        return {
            "status": "success",
            "message": f"Servidor para match {session_id} está activo",
            "container_id": container.short_id,
            "state": container.status
        }
    except NotFound:
        raise HTTPException(status_code=404, detail=f"No se encontró un servidor para sesión {session_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener estado del contenedor: {str(e)}")

@app.post("/admin/tokens/bulk-import", tags=["Admin"])
def api_bulk_import_tokens(payload: list[str], admin_secret: str):
    """
    Permite al Administrador pegar una lista de tokens SRCDS.
    Ignora automáticamente los duplicados.
    """
    if admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="No autorizado.")

    tokens_ingresados = payload
    if not tokens_ingresados:
        raise HTTPException(status_code=400, detail="La lista de tokens está vacía.")

    guardados = 0
    duplicados = 0

    with Session(engine) as session:
        for token_str in tokens_ingresados:
            # Limpiamos espacios en blanco o saltos de línea invisibles por las dudas
            token_limpio = token_str.strip()
            if not token_limpio:
                continue

            # Verificamos si el token ya existe en la DB antes de insertarlo
            existe = session.get(SRCDSPool, token_limpio)
            if not existe:
                nuevo_token = SRCDSPool(token=token_limpio)
                session.add(nuevo_token)
                guardados += 1
            else:
                duplicados += 1
        
        session.commit()

    return {
        "status": "success",
        "message": "Proceso de importación masiva finalizado.",
        "tokens_nuevos_guardados": guardados,
        "tokens_ignorados_por_duplicado": duplicados
    } 

@app.post("/admin/matches/purge", tags=["Admin"])
def api_purge_matches(admin_secret: str):
    """
    Busca sesiones marcadas como online que su contenedor ya no existe, libera los puertos y token y los marca como destroyed
    """
    if admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="No autorizado.")
    cantidad_purgada = 0
    with Session(engine) as session:
        selectable_sessions = session.exec(select(Match).where(or_(Match.status == statuses.online, Match.status == statuses.creating, Match.status == statuses.stopping, Match.status == statuses.error))).all()
        
        for match in selectable_sessions:
            try:
                docker_client.containers.get(str(match.container_id))
            except NotFound:
                # Si el contenedor no existe, hacemos limpieza de recursos y actualizamos estado
                release_ports(match.session_id)
                release_token(match.session_id)
                match.status = statuses.destroyed
                match.destroyed_at = datetime.now().isoformat()
                session.add(match)
                cantidad_purgada = cantidad_purgada + 1
        session.commit()
            

    return {
        "status": "success",
        "message": f"Proceso de purga finalizado. {cantidad_purgada} registros desincronizados eliminados."
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)