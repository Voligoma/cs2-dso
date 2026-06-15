
import time
import re
import requests
from rcon_manager import execute_rcon_command

def obtener_cantidad_jugadores(texto_status):
    """
    Usa expresiones regulares para parsear la línea de 'players' del comando status.
    Ejemplo de línea de Valve: 'players : 0 humans, 0 bots (10 max)'
    """
    match = re.search(r"players\s*:\s*(\d+)\s*humans", texto_status)
    if match:
        return int(match.group(1))
    return 0

def revisar_y_limpiar_partida(match_id, puerto_rcon, password):
    print(f"[Monitor-Match-{match_id}] Verificando estado...")
    
    # 1. Le pedimos el status al servidor por RCON
    info_status = execute_rcon_command(puerto_rcon, password, "status")
    
    # Si el RCON falla (porque el servidor se cayó o todavía está cargando), no hacemos nada
    if "Error" in info_status:
        print(f"[Monitor-Match-{match_id}] Servidor no responde por RCON todavía.")
        return False

    # 2. Analizar cuántos jugadores hay adentro
    jugadores_activos = obtener_cantidad_jugadores(info_status)
    print(f"[Monitor-Match-{match_id}] Jugadores actuales: {jugadores_activos}")

    # 3. LÓGICA DE AUTO-DESTRUCCIÓN: 
    # Para la prueba, si hay 0 jugadores, asumimos que terminó y lo borramos.
    # (En producción acá chequearías si el score llegó a 13 o si pasaron 15 mins vacíos).
    if jugadores_activos == 0:
        print(f"🚨 [Monitor-Match-{match_id}] ¡Partida finalizada o vacía! Iniciando destrucción...")
        
        print(f"✅ [Monitor-Match-{match_id}] Recursos liberados con éxito (Puerto {puerto_rcon} libre).")
            
    return False

# =========================================================================
# BUCLE PRINCIPAL DE MONITOREO (Simulación de un proceso de fondo)
# =========================================================================
if __name__ == "__main__":
    # Datos del match de prueba que tengas corriendo ahora
    MATCH_A_MONITOREAR = 1
    PUERTO_RCON_TEST = 27020
    CLAVE_RCON_TEST = "changeme"

    print(f"Iniciando el Monitor en segundo plano para el Match {MATCH_A_MONITOREAR}...")
    print("Presioná Ctrl+C para apagar el monitor.\n")
    
    while True:
        partida_eliminada = revisar_y_limpiar_partida(
            MATCH_A_MONITOREAR, 
            PUERTO_RCON_TEST, 
            CLAVE_RCON_TEST
        )
        
        if partida_eliminada:
            print("Monitoreo finalizado para este match.")
            break
            
        # Esperamos 10 segundos antes de volver a preguntar (en producción pueden ser 30s o 1 min)
        print("Esperando 10 segundos para la próxima revisión...\n")
        time.sleep(10)