import logging
from mega import (MegaTransferListener, MegaError)
import os
import shutil
import urllib.request
import urllib.parse
import json

'''def radarr_request(endpoint, method='GET', data=None):
    """
    Función base para comunicarse con la API de Radarr v3.
    """
    # Cambia 'radarr' por la IP si sigues teniendo problemas de red, 
    # pero 'http://radarr:7878' es lo correcto dentro de Docker.
    #BASE_URL = "http://radarr:7878/api/v3" 
    #API_KEY = "TU_RADARR_API_KEY" # <--- ¡Pon aquí tu clave real!
    API_KEY = "155fd6544b034bcea74ba72f5948ce04"
    BASE_URL = f"http://192.168.1.152f:7878/api/v3"
    url = f"{BASE_URL}/{endpoint}"

    # Preparar el cuerpo si hay datos (POST)
    body = json.dumps(data).encode('utf-8') if data else None

    # Crear la petición
    req = urllib.request.Request(url, data=body, method=method)

    # Cabeceras obligatorias
    req.add_header('Content-Type', 'application/json')
    req.add_header('X-Api-Key', API_KEY)

    # Ejecutar
    with urllib.request.urlopen(req) as response:
        # Devolvemos el JSON decodificado
        return json.loads(response.read().decode('utf-8'))
    
def auto_import_radarr(file_path, save_to):

    carpeta_padre = os.path.dirname(file_path)
    file_path = os.path.abspath(file_path)
   
    # 1. Escaneamos la carpeta
    resultados = radarr_request(f"manualimport?folder={urllib.parse.quote(carpeta_padre)}&filterExistingFiles=false")
    archivo_a_importar = next((r for r in resultados if r['path'] == file_path), None)

    if not archivo_a_importar:
        logging.info("Radarr aún no ve este archivo.")
        return

    movie_id = None

    # 2. Si ya reconoce la peli, usamos su ID
    if archivo_a_importar.get('movie'):
        movie_id = archivo_a_importar['movie']['id']
    else:
        # 3. SI NO LA CONOCE: Buscamos en TMDB y la creamos!
        file_name = os.path.basename(file_path) #os.path.basename(carpeta_padre)
        logging.info(f"Buscando info para crear '{file_name}' en Radarr...")
        busqueda = radarr_request(f"movie/lookup?term={urllib.parse.quote(file_name)}")

        if busqueda:
            pelicula_encontrada = busqueda[0]
          
            nombre_oficial = f"{pelicula_encontrada['title']} ({pelicula_encontrada['year']})"
            base_dir = os.path.dirname(os.path.normpath(file_path))
            target_dir = os.path.join(save_to, nombre_oficial)
            logging.info(target_dir)
            try:
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir, exist_ok=True)
                    logging.info(f"Carpeta creada: {target_dir}")
                else:
                     logging.info(f"La carpeta ya existe, continuando...")
            except Exception as e:
                logging.info(f"❌ Error crítico creando carpeta {target_dir}: {e}")
            # Si ya existe, movemos el contenido dentro (y luego borramos la vacía)
            for item in os.listdir(carpeta_padre):
                shutil.move(os.path.join(carpeta_padre, item), target_dir)
    

            \'\'\'# Creamos la peli en Radarr
            nueva_peli = radarr_request("movie", method='POST', data={
                "title": pelicula_encontrada['title'],
                "tmdbId": pelicula_encontrada['tmdbId'],
                "year": pelicula_encontrada['year'],
                "qualityProfileId": 1,
                "rootFolderPath": "/downloads/films", # RUTA DONDE QUIERES GUARDARLAS
                "monitored": True,
                "addOptions": {"searchForMovie": False}
            })\'\'\'
            nuevo_path = os.path.join(target_dir, file_name)

            # 3.6. Forzamos un re-escaneo de la nueva carpeta para que Radarr la vea
            radarr_request("command", method='POST', data={
                "name": "RescanFolder",
                "folder": target_dir
            })
            # Damos tiempo a Radarr para que procese el nuevo path
            import time
            time.sleep(3) 

            # 4. Importamos usando el nuevo path y el movie_id
            if movie_id:
                import_payload = [{
                    "path": nuevo_path,  # <--- USAMOS LA RUTA NUEVA
                    "movieId": movie_id,
                    "quality": archivo_a_importar['quality'],
                    "importMode": "move"
                }]
                radarr_request("manualimport", method='POST', data=import_payload)
                logging.info(f"✅ Película importada a Radarr desde: {nuevo_path}")
            
            #movie_id = nueva_peli['id']
            logging.info(f"Película '{pelicula_encontrada['title']}' creada con éxito.")

    # 4. Importamos
    if movie_id:
        import_payload = [{
            "path": archivo_a_importar['path'],
            "movieId": movie_id,
            "quality": archivo_a_importar['quality'],
            "importMode": "move"
        }]
        radarr_request("manualimport", method='POST', data=import_payload)
        logging.info(f"✅ Película importada a Radarr.")
        
def radarr_import(file_path):
 
    API_KEY = "155fd6544b034bcea74ba72f5948ce04"
    API_URL = f"http://192.168.1.152:7878/api/v3/command?apikey={API_KEY}"
    
    base_dir = os.path.dirname(file_path)
    file_name = os.path.basename(file_path)
    base_name = os.path.splitext(file_name)[0]
    job_dir = os.path.join(base_dir, f"{base_name}.job")

    if not os.path.exists(job_dir):
        os.makedirs(job_dir)

    # 3. Mover el archivo a la carpeta .job
    target_path = os.path.join(job_dir, file_name)
    shutil.move(file_path, target_path)

    # 4. Avisar a Radarr
    data = {
        "name": "DownloadedMoviesScan",
        "path": job_dir
    }

    data_json = json.dumps(data).encode('utf-8')

    # 3. Preparar la petición
    req = urllib.request.Request(API_URL, data=data_json, method='POST')

    # 4. Añadir las cabeceras necesarias
    req.add_header('Content-Type', 'application/json')
    #req.add_header('X-Api-Key', API_KEY)

    # 5. Ejecutar la petición
    try:
        with urllib.request.urlopen(req) as response:
            result = response.read().decode('utf-8')
        print(f"Radarr notified: {response.status}")
    except Exception as e:
        print(f"Error contacting Radarr: {e}")'''
        
def radarr_request(endpoint, method='GET', data=None):
    """
    Función base para comunicarse con la API de Radarr v3.
    """
    # Cambia 'radarr' por la IP si sigues teniendo problemas de red, 
    # pero 'http://radarr:7878' es lo correcto dentro de Docker.
    #BASE_URL = "http://radarr:7878/api/v3" 
    #API_KEY = "TU_RADARR_API_KEY" # <--- ¡Pon aquí tu clave real!
    API_KEY = "155fd6544b034bcea74ba72f5948ce04"
    BASE_URL = f"http://radarr.local/api/v3"
    url = f"{BASE_URL}/{endpoint}"

    # Preparar el cuerpo si hay datos (POST)
    body = json.dumps(data).encode('utf-8') if data else None

    # Crear la petición
    req = urllib.request.Request(url, data=body, method=method)

    # Cabeceras obligatorias
    req.add_header('Content-Type', 'application/json')
    req.add_header('X-Api-Key', API_KEY)

    # Ejecutar
    with urllib.request.urlopen(req) as response:
        # Devolvemos el JSON decodificado
        return json.loads(response.read().decode('utf-8'))
    
def auto_import_radarr(file_path, save_to):

    carpeta_padre = os.path.dirname(file_path)
    file_path = os.path.abspath(file_path)
   
    # 1. Escaneamos la carpeta
    resultados = radarr_request(f"manualimport?folder={urllib.parse.quote(carpeta_padre)}&filterExistingFiles=false")
    archivo_a_importar = next((r for r in resultados if r['path'] == file_path), None)

    if not archivo_a_importar:
        logging.info("Radarr aún no ve este archivo.")
        return

    movie_id = None

    # 2. Si ya reconoce la peli, usamos su ID
    if archivo_a_importar.get('movie'):
        movie_id = archivo_a_importar['movie']['id']
    else:
        # 3. SI NO LA CONOCE: Buscamos en TMDB y la creamos!
        file_name = os.path.basename(file_path) #os.path.basename(carpeta_padre)
        logging.info(f"Buscando info para crear '{file_name}' en Radarr...")
        busqueda = radarr_request(f"movie/lookup?term={urllib.parse.quote(file_name)}")

        if busqueda:
            pelicula_encontrada = busqueda[0]
          
            nombre_oficial = f"{pelicula_encontrada['title']} ({pelicula_encontrada['year']})"
            base_dir = os.path.dirname(os.path.normpath(file_path))
            target_dir = os.path.join(save_to, nombre_oficial)
            logging.info(target_dir)
            try:
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir, exist_ok=True)
                    logging.info(f"Carpeta creada: {target_dir}")
                else:
                     logging.info(f"La carpeta ya existe, continuando...")
            except Exception as e:
                logging.info(f"❌ Error crítico creando carpeta {target_dir}: {e}")
            # Si ya existe, movemos el contenido dentro (y luego borramos la vacía)
            for item in os.listdir(carpeta_padre):
                shutil.move(os.path.join(carpeta_padre, item), target_dir)
    

            # Creamos la peli en Radarr
            nueva_peli = radarr_request("movie", method='POST', data={
                "title": pelicula_encontrada['title'],
                "tmdbId": pelicula_encontrada['tmdbId'],
                "year": pelicula_encontrada['year'],
                "qualityProfileId": 1,
                "rootFolderPath": save_to,
                "monitored": True,
                "addOptions": {"searchForMovie": False}
            })
            movie_id = nueva_peli['id']
            nuevo_path = os.path.join(target_dir, file_name)

            '''# 3.6. Forzamos un re-escaneo de la nueva carpeta para que Radarr la vea
            radarr_request("command", method='POST', data={
                "name": "RescanFolder",
                "folder": target_dir
            })
            # Damos tiempo a Radarr para que procese el nuevo path
            import time
            time.sleep(3) '''

            # 4. Importamos usando el nuevo path y el movie_id
            if movie_id:
                import_payload = [{
                    "path": nuevo_path,  # <--- USAMOS LA RUTA NUEVA
                    "movieId": movie_id,
                    "quality": archivo_a_importar['quality'],
                    "importMode": "move"
                }]
                radarr_request("manualimport", method='POST', data=import_payload)
                logging.info(f"✅ Película importada a Radarr desde: {nuevo_path}")
            
            #movie_id = nueva_peli['id']
            logging.info(f"Película '{pelicula_encontrada['title']}' creada con éxito.")
        
class TransferListener(MegaTransferListener):
    def __init__(self):
        self.is_finished = False
        self.over_quota = False
        self.error = None
        self.transfer_name = None
        self.total_size = None
        self.speed = 0
        self.smooth_speed = 0
        self.transfered_size = 0
        super(TransferListener, self).__init__()

    def onTransferStart(self, api, transfer):
        filename = transfer.getFileName()
        if len(filename) > 24:
            self.transfer_name = filename[:21] + '...'
        else:
            self.transfer_name = filename + ' ' * (21-len(filename))
        self.total_size = transfer.getTotalBytes()
        logging.info('Transfer start ({})'.format(transfer.getType()))
    
    def onTransferFinish(self, api, transfer, error):
        self.is_finished = True
        if error.getErrorCode() != MegaError.API_OK:
            self.error = error.toString()
        self.speed = transfer.getMeanSpeed()
        logging.info('Transfer finished ({}); Result: {}'
                     .format(transfer, transfer.getFileName(), error))
        path = transfer.getPath()
        try:
            # 0o664 is rw-rw-r--
            os.chmod(path, 0o664)
            logging.info(f"Permissions changed to 664 at: {path}")
        except Exception as e:
            logging.error(f"Error changing permisions: {e}")
        auto_import_radarr(path, '/downloads/films')

    def onTransferTemporaryError(self, api, transfer, error):
        try:
            self.error = error.toString()
            logging.info('Transfer temporary error ({} {}); Error: {}'
                         .format(transfer, transfer.getFileName(), error))
            if error.getErrorCode() == MegaError.API_EINCOMPLETE:
                logging.info('Download incomplete, retrying...')
                #api.retryTransfer(transfer)
            if error.getErrorCode() == MegaError.API_EOVERQUOTA:
                self.over_quota = True
                logging.info('Download incomplete, retrying...')
                #api.retryTransfer(transfer)
            else:
                logging.warning(f'Unhandled error code: {error}')
        except Exception as e:
            logging.error(f"Error in onTransferTemporaryError: {e}")
            logging.debug(f"Error object: {error}, Type: {type(error)}")

    def onTransferUpdate(self, api, transfer):
        self.speed = transfer.getSpeed()
        self.smooth_speed = self.speed*0.02+self.smooth_speed*0.98
        self.transfered_size = max(self.transfered_size, transfer.getTransferredBytes())
        logging.info('Transfer update ({} {});'
                     ' Progress: {} KB of {} KB, {} KB/s'
                     .format(transfer,
                             transfer.getFileName(),
                             transfer.getTransferredBytes() / 1024,
                             transfer.getTotalBytes() / 1024,
                             transfer.getSpeed() / 1024))

    def getStatus(self, size=25):
        if self.error:
            print(self.error)
            return f'{self.transfer_name}: \u001b[0;31m{self.error}\u001b[0;0m'
        self.over_quota = False
        if self.is_finished:
            return f"{self.transfer_name} is done downloading with an average speed of {self.speed/(1024*1024):0.2f} MB/s"
        progress = self.transfered_size/self.total_size
        x = int(size*progress)
        if self.smooth_speed == 0:
            time_str = 'inf'
        else:
            remaining = (self.total_size - self.transfered_size) /self.smooth_speed
            mins, sec = divmod(remaining, 60)
            time_str = f"{int(mins):02}:{int(sec):02}"
        return f"{self.transfer_name}: {(self.speed/(1024*1024)):0.2f} MB/s [\u001b[0;31m{u'█'*x}\u001b[0;0m{u'▒'*(size-x)}] {int(progress*100)} % Est. {time_str}"