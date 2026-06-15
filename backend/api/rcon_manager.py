from rcon.source import Client
import time

def execute_rcon_command(rcon_port, password, command, ip="127.0.0.1"):
    """
    Se conecta al servidor de CS2 por RCON, ejecuta un comando y devuelve la respuesta.
    """
    try:
        with Client(ip, rcon_port, passwd=password) as client:
            response = client.run(command)
        print(response)
        return response
    except Exception as e:
        return f"Error al conectar por RCON al servidor {ip}:{rcon_port}: {e}"

# =========================================================================
# PRUEBA DE FUEGO EN CALIENTE
# =========================================================================
if __name__ == "__main__":
    # IMPORTANTE: Estos datos tienen que coincidir con el contenedor que tengas prendido.
    # En el ejemplo de la API anterior usamos:
    PUERTO_RCON_TEST = 27017  # El puerto RCON de tu match de prueba
    CLAVE_RCON_TEST = "changeme"

    print("--- 1. Enviando un mensaje global al chat del juego ---")
    cmd_say = "say [SISTEMA] Backend conectado con exito. La partida comenzara pronto."
    res = execute_rcon_command(PUERTO_RCON_TEST, CLAVE_RCON_TEST, cmd_say)
    print(f"Respuesta del servidor: {res}\n")

    time.sleep(1) # Esperamos un segundo

    print("--- 2. Pidiendo el estado del servidor (status) ---")
    # Este comando te devuelve cuántos jugadores hay, el mapa actual, los pings, etc.
    res_status = execute_rcon_command(PUERTO_RCON_TEST, CLAVE_RCON_TEST, "status")
    print(f"Respuesta del servidor:\n{res_status}\n")

    time.sleep(1)

    print("--- 3. Forzando reinicio de la partida (mp_restartgame) ---")
    # Comando típico de CS para reiniciar la ronda en 1 segundo
    res_restart = execute_rcon_command(PUERTO_RCON_TEST, CLAVE_RCON_TEST, "mp_restartgame 1")
    print(f"Respuesta del servidor: {res_restart}\n")