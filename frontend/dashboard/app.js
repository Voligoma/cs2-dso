// Esperamos a que Alpine.js se inicialice para registrar nuestro componente
document.addEventListener('alpine:init', () => {
    
    Alpine.data('orchestrator', () => ({
        // Variables de estado
        backendUrl: 'http://192.168.1.11:8000', 
        matches: [], 
        serverName: '',
        mapaInicial: 'de_inferno',
        loading: false,

        // Función para traer todos los matches del Backend
        async fetchMatches() {
            try {
                let response = await fetch(`${this.backendUrl}/matches`);
                this.matches = await response.json();
            } catch (err) {
                alert('Error conectando al backend: ' + err.message);
            }
        },

        // Función para lanzar un servidor automáticamente
        async launchServer() {
            if (!this.serverName.trim()) return alert('Escribí un nombre para el servidor.');
            this.loading = true;
            try {
                let response = await fetch(`${this.backendUrl}/matches/autolaunch`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        server_name: this.serverName,
                        mapa_inicial: this.mapaInicial 
                    })
                });
                if (response.ok) {
                    this.serverName = '';
                    await this.fetchMatches(); // Refrescar lista
                } else {
                    let errData = await response.json();
                    alert('Error: ' + JSON.stringify(errData.detail));
                }
            } catch (err) {
                alert('Error al lanzar: ' + err.message);
            } finally {
                this.loading = false;
            }
        },

        // Función para apagar un servidor
        async destroyServer(sessionId) {
            if (!confirm('¿Estás seguro de apagar este servidor?')) return;
            try {
                await fetch(`${this.backendUrl}/matches/destroy?session_id=${sessionId}`, { method: 'POST' });
                await this.fetchMatches();
            } catch (err) {
                alert('Error al destruir: ' + err.message);
            }
        },
        
    }));
    
});