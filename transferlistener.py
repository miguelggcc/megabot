import logging
from mega import (MegaTransferListener, MegaError)
import os

class TransferListener(MegaTransferListener):

    def __init__(self, radarr_api=None):
        self.is_finished = False
        self.over_quota = False
        self.error = None
        self.transfer_name = None
        self.total_size = None
        self.speed = 0
        self.smooth_speed = 0
        self.transfered_size = 0
        self.radarr_api = radarr_api
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
        if self.radarr_api:
            self.radarr_api.auto_import_radarr(path, '/downloads/films')

    def onTransferTemporaryError(self, api, transfer, error):
        try:
            self.error = error.toString()
            logging.info('Transfer temporary error ({} {}); Error: {}'
                         .format(transfer, transfer.getFileName(), error))
            if error.getErrorCode() == MegaError.API_EINCOMPLETE:
                logging.info('Download incomplete, retrying...')
                # api.retryTransfer(transfer)
            if error.getErrorCode() == MegaError.API_EOVERQUOTA:
                self.over_quota = True
                logging.info('Download incomplete, retrying...')
                # api.retryTransfer(transfer)
            else:
                logging.warning(f'Unhandled error code: {error}')
        except Exception as e:
            logging.error(f"Error in onTransferTemporaryError: {e}")
            logging.debug(f"Error object: {error}, Type: {type(error)}")

    def onTransferUpdate(self, api, transfer):
        self.speed = transfer.getSpeed()
        self.smooth_speed = self.speed*0.02+self.smooth_speed*0.98
        self.transfered_size = max(
            self.transfered_size, transfer.getTransferredBytes())
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
            remaining = (self.total_size - self.transfered_size) / \
                self.smooth_speed
            mins, sec = divmod(remaining, 60)
            time_str = f"{int(mins):02}:{int(sec):02}"
        return f"{self.transfer_name}: {(self.speed/(1024*1024)):0.2f} MB/s [\u001b[0;31m{u'█'*x}\u001b[0;0m{u'▒'*(size-x)}] {int(progress*100)} % Est. {time_str}"
