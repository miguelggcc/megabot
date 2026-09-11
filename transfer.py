from mega import MegaTransfer

class Transfer(MegaTransfer):
    def __init__(self):
        self.name = None
        self.tag = None
        self.smooth_speed = 0
        self.is_finished = False
        self.over_quota = False
        self.error = None
        super(MegaTransfer, self).__init__()
        
    def getStatus(self, size=25):
        if self.error:
            print(self.error)
            return f'{self.name}: \u001b[0;31m{self.error}\u001b[0;0m'
        if self.is_finished:
            return f"{self.name} is done downloading with an average speed of {self.getMeanSpeed()/(1024*1024):0.2f} MB/s"
        progress = self.getTransferredBytes()/self.getTotalBytes()
        x = int(size*progress)
        if self.smooth_speed == 0:
            time_str = 'inf'
        else:
            remaining = (self.getTotalBytes() - self.getTransferredBytes()) /self.smooth_speed
            mins, sec = divmod(remaining, 60)
            time_str = f"{int(mins):02}:{int(sec):02}"
        return f"{self.name}: {(self.getSpeed()/(1024*1024)):0.2f} MB/s [\u001b[0;31m{u'█'*x}\u001b[0;0m{u'▒'*(size-x)}] {int(progress*100)} % Est. {time_str}"
