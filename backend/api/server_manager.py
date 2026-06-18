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

from rcon_manager import execute_rcon_command
ADMIN_SECRET = "changeme"  # Change this for a real password in production
app = FastAPI(title="CS2 Orchestrator API")
# =========================================================================
# internal Functions
# =========================================================================

def seed_port_pool():
    """
    Executes every time the backend is run. If needed, 
    it creates the inventory of allowed ports for the servers.
    """
    with Session(engine) as session:
        # Checks if there is anything in the PortPool Table
        existing_ports = session.exec(select(PortPool)).first()
        
        if not existing_ports:
            print("📦 [PortPool] Empty port pool detected. Filling port pool...")
            
            RANGE_START = 27100
            MAX_SERVER_QTY = 50  # Levantamos hasta 50 servidores en simultáneo
            
            for i in range(MAX_SERVER_QTY):
                game_p = RANGE_START + (i * 3)
                tv_p = game_p + 1
                rcon_p = game_p + 2
                
                new_block = PortPool(
                    game_port=game_p,
                    tv_port=tv_p,
                    rcon_port=rcon_p,
                    in_use=False
                )
                session.add(new_block)
            
            session.commit()
            print(f"✅ [PortPool] {MAX_SERVER_QTY} Blocks ready to use.")
        else:
            print("📦 [PortPool] PortPool already filled, skiping...")

def get_free_ports(session_id:str):
    """
    Searches for a free 3 port block in the port pool
    and if avaible reserves the block to the session_id provided.
    """
    
    with Session(engine) as session:
        free_port = session.exec(select(PortPool).where(PortPool.in_use == False)).first()
        if not free_port:
            raise HTTPException(status_code=500, detail="Not enough ports avaible")
        # Mark ports as used
        free_port.in_use = True
        free_port.assigned_session_id = session_id
        game_port = free_port.game_port
        session.add(free_port)
        session.commit()
        
        return game_port

def release_ports(session_id:str):
    """
    Realeases the reserved ports by the provided session_id,
    making it avaible for reuse
    """
    
    with Session(engine) as session:
        port = session.exec(select(PortPool).where(PortPool.assigned_session_id == session_id)).first()
        if not port:
            raise HTTPException(status_code=500, detail="Port is not in port pool")
         # Mark ports as not used
        port.in_use = False
        port.assigned_session_id = None
        session.add(port)
        session.commit()
        
        return 1

def reserve_ports(session_id:str, game_port:int):
    """
    Let's you manually reserve a custom 3 port block in the port pool
    the range is the game port and the other 2 consecutive numbers.
    Returns 1 if succesfully reserved
    """
    
    with Session(engine) as session:
        port = session.exec(select(PortPool).where(PortPool.game_port == game_port)).first()
        if not port:
            raise HTTPException(status_code=404, detail="Requested port is not in port pool")
        if port.in_use:
            raise HTTPException(status_code=500, detail="Requested port is already in use")
        # Mark ports as used
        port.in_use = True
        port.assigned_session_id = session_id
        port.game_port = game_port
        port.tv_port = game_port + 1
        port.rcon_port = game_port + 2
        session.add(port)
        session.commit()
        
        return 1

def get_free_token(session_id:str):
    """
    Searches for a free SRCDS key/token in the token pool
    and if avaible reserves token to the session_id provided.
    """
    
    with Session(engine) as session:
        free_token = session.exec(select(SRCDSPool).where(SRCDSPool.in_use == False)).first()
        if not free_token:
            raise HTTPException(status_code=500, detail="Not enough tokens avaible")
        # Mark tokens as used
        free_token.in_use = True
        free_token.assigned_session_id = session_id
        token = free_token.token
        session.add(free_token)
        session.commit()
        
        return token

def reserve_token(session_id:str, token:str):
    """
    Let's you manually reserve a custom SRDCDS token in the token pool.
    Also allows to reserve a token that is not in the pool, in that case 
    the token will not be reserved in any database.
    Returns 1 if succesfully reserved or if not found.
    """
    with Session(engine) as session:
        token_entry = session.exec(select(SRCDSPool).where(SRCDSPool.token == token)).first()
        if not token_entry:
            return 1
        if token_entry.in_use:
            raise HTTPException(status_code=500, detail="Requested token already in use")
        # Mark tokens as not used
        token_entry.in_use = True
        token_entry.assigned_session_id = session_id
        session.add(token_entry)
        session.commit()
        
        return 1

def release_token(session_id:str):
    """
    Realeases the reserved token by the provided session_id,
    making it avaible for reuse.
    """
    with Session(engine) as session:
        token = session.exec(select(SRCDSPool).where(SRCDSPool.assigned_session_id == session_id)).first()
        if not token:
            raise HTTPException(status_code=500, detail="Token is not in port pool")
        # Mark tokens as not used
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
    """Base match table"""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    
    srcds_token: Optional[str] = None
    game_port: Optional[int] = None
    tv_port: Optional[int] = None
    rcon_port: Optional[int] = None
    
    container_id: Optional[str] = None
    status: statuses = Field(default=statuses.creating)
    players: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    destroyed_at: str = ""

class PortPool(SQLModel, table=True):
    """Inventory of ports for servers"""
    game_port: int = Field(primary_key=True)
    assigned_session_id: Optional[str] = Field(default=None, unique=True)
    tv_port: int
    rcon_port: int
    in_use: bool = Field(default=False)

class SRCDSPool(SQLModel, table=True):
    """nventory of SRDCS keys/tokens for servers"""
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
    print(f"Error connecting to Docker deamon: {e}")
    exit(1)


# =========================================================================
# API
# =========================================================================

@app.post("/matches/launch")
def api_launch_server(config: MatchCreate):
    """
    Launches a new CS2 server instance with the most configurable options.
    """
    session_id = str(uuid.uuid4())
    
    reserve_ports(session_id, config.game_port)
    reserve_token(session_id, config.srcds_token)
    
    # 1
    with Session(engine) as session:
        new_match = Match.model_validate(config)
        new_match.session_id = session_id
        game_port = config.game_port
        new_match.tv_port = game_port + 1
        new_match.rcon_port = game_port + 2
        session.add(new_match)
        session.commit()
        session.refresh(new_match)
        
        session_id = new_match.session_id

    # 2.
    actual_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.abspath(os.path.join(actual_dir, "../../cs2-server-base"))
    
    steamcmd_cache = f"{base_dir}/steamcmd-cache"
    steam_cache = f"{base_dir}/steam-cache"
    
    os.makedirs(steamcmd_cache, exist_ok=True)
    os.makedirs(steam_cache, exist_ok=True)

    print(f"[Match-{session_id}] Preparando contenedor en Python...")

    try:
        # 3.
        container = docker_client.containers.run(
            image='joedwards32/cs2',
            name=f"cs2-match-{session_id}",
            detach=True,
            stdin_open=True,
            tty=True,
            environment={
                "session_id": session_id,
                "SRCDS_TOKEN": new_match.srcds_token,
                "CS2_SERVERNAME": new_match.server_name,
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
                '27015/tcp': new_match.game_port,
                '27015/udp': new_match.game_port,
                '27020/udp': new_match.tv_port,
                '27017/tcp': new_match.rcon_port
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
    """
    Launches a new CS2 server instance with only with the name, auto-assigning ports and token.
    """
    
    # 1. Register everything in the db
    with Session(engine) as session:
        
        session_id = str(uuid.uuid4())
        
        game_port = get_free_ports(session_id)
        srcds_token = get_free_token(session_id)
        
        new_match = Match.model_validate(config)
        
        new_match.session_id = session_id
        new_match.srcds_token = srcds_token
        new_match.game_port = game_port
        new_match.tv_port = game_port + 1
        new_match.rcon_port = game_port + 2
        new_match.status = statuses.creating
        
        session.add(new_match)
        session.commit()
        session.refresh(new_match)
        
    # 2. Calculate CS2 files directory
    actual_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.abspath(os.path.join(actual_dir, "../../cs2-server-base"))
    
    steamcmd_cache = f"{base_dir}/steamcmd-cache"
    steam_cache = f"{base_dir}/steam-cache"
    
    os.makedirs(steamcmd_cache, exist_ok=True)
    os.makedirs(steam_cache, exist_ok=True)

    print(f"[Match-{session_id}] Preparando contenedor en Python...")

    try:
        # 3. Launch docker instace
        container = docker_client.containers.run(
            image='joedwards32/cs2',
            name=f"cs2-match-{session_id}",
            detach=True,
            stdin_open=True,
            tty=True,
            environment={
                "session_id": session_id,
                "SRCDS_TOKEN": new_match.srcds_token,
                "CS2_SERVERNAME": new_match.server_name,
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
                '27015/tcp': new_match.game_port,
                '27015/udp': new_match.game_port,
                '27020/udp': new_match.tv_port,
                '27017/tcp': new_match.rcon_port
            }
        )

        # 4. Update state to Online and return to API
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
        # If failure, is registered in the DB as Error
        with Session(engine) as session:
            db_match = session.get(Match, session_id)
            if db_match:
                db_match.status = statuses.error
                session.add(db_match)
                session.commit()
        raise HTTPException(status_code=500, detail=f"Error al crear contenedor: {str(e)}")

@app.get("/matches")
def api_listar_matches(status: Optional[statuses] = None):
    """
    Allows to request a list of all the instances with full details,
    also allows to filter by state.
    """
    
    with Session(engine) as session:
        query = select(Match)
        if status is not None:
            query = query.where(Match.status == status)
        matches = session.exec(query).all()
        return matches

@app.post("/matches/destroy")
def api_destroy_server(session_id: str):
    """
    Destroys a instances providing the session_id
    """
    
    try:
        container_name = f"cs2-match-{session_id}"
        container = docker_client.containers.get(container_name)
        current_session_id = None
        
        # Update state to Stopping
        with Session(engine) as session_db:
            db_match = session_db.get(Match, session_id)
            if db_match:
                db_match.status = statuses.stopping
                session_db.add(db_match)
                session_db.commit()

        print(f"[Docker] Stopping {container_name}...")
        container.stop(timeout=10)
        
        print(f"[Docker] Dealeting {container_name}...")
        container.remove()
        
        # Update state to Destroyed
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
            "message": f"Server for match {session_id} destroyed",
            "session_id": current_session_id,
            "container_id": container.short_id,
        }
    except NotFound:
        raise HTTPException(status_code=404, detail=f"No server was found for match {session_id}")        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occured while trying to delete the server: {str(e)}")

@app.get("/matches/get_server_status")
def api_get_server_status(session_id: str):
    """
    Gets a specific instace status providing the id.
    """
    
    try:
        container_name = f"cs2-match-{session_id}"
        container = docker_client.containers.get(container_name)
        return {
            "status": "success",
            "message": f"Server for match {session_id} is active",
            "container_id": container.short_id,
            "state": container.status
        }
    except NotFound:
        raise HTTPException(status_code=404, detail=f"No server was found for match {session_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occured while trying to obtain server info: {str(e)}")

@app.post("/admin/tokens/bulk-import", tags=["Admin"])
def api_bulk_import_tokens(payload: list[str], admin_secret: str):
    """
    Allows admin user to bulk add SRDCS token (WIP)
    """
    if admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Not Authorized")

    tokens_ingresados = payload
    if not tokens_ingresados:
        raise HTTPException(status_code=400, detail="Token list is empty!")

    guardados = 0
    duplicados = 0

    with Session(engine) as session:
        for token_str in tokens_ingresados:
            # Clear blank spaces
            token_limpio = token_str.strip()
            if not token_limpio:
                continue

            # Varify if token is already in DB
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
        "message": "Importation finalized",
        "new_tokens_stored": guardados,
        "ignored_duplicated_tokens": duplicados
    } 

@app.post("/admin/matches/purge", tags=["Admin"])
def api_purge_matches(admin_secret: str):
    """
    Searches for orphan matches in the DB, if no docker instance is online,
    it deletes them realising the ports and tokens.
    """
    if admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Not Authorized")
    purged_qty = 0
    with Session(engine) as session:
        selectable_sessions = session.exec(select(Match).where(or_(Match.status == statuses.online, Match.status == statuses.creating, Match.status == statuses.stopping, Match.status == statuses.error))).all()
        
        for match in selectable_sessions:
            try:
                docker_client.containers.get(str(match.container_id))
            except NotFound:
                release_ports(match.session_id)
                release_token(match.session_id)
                match.status = statuses.destroyed
                match.destroyed_at = datetime.now().isoformat()
                session.add(match)
                purged_qty = purged_qty + 1
        session.commit()
            

    return {
        "status": "success",
        "message": f"Purge process finalized. {purged_qty} unsynced registries deleted"
    }

@app.post("/admin/matches/destroyall", tags=["Admin"])
def api_destroy_all_servers(admin_secret: str):
    """
    Stops and deletes all the instances.
    """
    if admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Not Authorized")
    deleted_qty = 0
    
    with Session(engine) as session:
        selectable_sessions = session.exec(select(Match).where(or_(Match.status == statuses.online, Match.status == statuses.creating, Match.status == statuses.stopping, Match.status == statuses.error))).all()
        
        for match in selectable_sessions:
            try:
                docker_client.containers.get(str(match.container_id))
                api_destroy_server(match.session_id)
                deleted_qty = deleted_qty + 1
            except NotFound:
                raise HTTPException(status_code=404, detail=f"No server found dor {match.session_id}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error while trying to delete container: {str(e)}")
        session.commit()
            

    return {
        "status": "success",
        "message": f"Deleting process finalized. {deleted_qty} servers deleted"
    }



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)