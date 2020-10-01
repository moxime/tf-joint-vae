import time
import numpy as np
import logging
import torch
import pandas as pd

def print_epoch(i, per_epoch, epoch, epochs, loss,
                snake='=>', blinker='o ', line_length=50,
                info='', end_of_epoch='\n'):

    steps = i * (line_length - len(info)) // per_epoch
    K = int(np.log10(epochs))+1
    Ki = int(np.log10(per_epoch))+1

    print('\r', end='')
    print(f'epoch {epoch+1:{K}d}/{epochs} ', end='')
    print('=' * steps + snake[i % len(snake)] +
          ' ' * (line_length - steps - len(info)) + f'{loss: .3e} {info}', end='')
    
    print(f' (batch {i+1:{Ki}d}/{per_epoch})',
          end = end_of_epoch if i == per_epoch - 1 else '')
    # print(f' {blinker[i%len(blinker)]}', end='')


def print_results(i, per_epoch, epoch, epochs,
                  loss_components=None,
                  losses=None,
                  acc_methods=(),
                  accuracies=None,
                  metrics=(),
                  measures=None,
                  time_per_i=0, batch_size=100,
                  preambule='',
                  end_of_epoch='\n'):

    bold_esc = '\033[1m'
    end_esc = ''
    if preambule == 'train':
        preambule = bold_esc + preambule
        end_esc = '\033[0m'
        
    no_loss = losses is None
    no_metrics = metrics is None
    
    Kep = 3
    Kn = 10
    num_format = {'default': '{' + f':^{Kn}.2e' + '}',
                  'snr': '{' + f':{Kn-4}.1f' + '} dB '}

    if epoch == -2:
        i = per_epoch - 1        
        preambule = f'{"epoch":_^{2 * Kep + 1}}_{preambule:_>5}_'
        if loss_components:
            length = len('|'.join(f'{k:^10}' for k in loss_components))
            loss_str = f'{"losses":_^{length}}'
        else: loss_str = ''
        if metrics:
            length = len('|'.join(f'{k:^10}' for k in metrics))
            metrics_str = f'{"metrics":_^{length}}'
        else: metrics_str = ''


    elif epoch == -1:
        i = per_epoch - 1
        preambule = f'{" ":^{2 * Kep + 1}} {preambule:>5} '

        if loss_components:
            length = len('|'.join(f'{k:^10}' for k in loss_components))
            loss_str = '|'.join(f'{k:^10}' for k in loss_components)
        else: loss_str = ''
        if metrics:
            length = len('|'.join(f'{k:^10}' for k in metrics))
            metrics_str = '|'.join(f'{k:^10}' for k in metrics)
        else: metrics_str=''
        """
        elif epoch == 0:
            preambule = f'{" ":^{2 * Kep + 1}} {preambule:>5} |'

            if loss_components:
                loss_str = '|'.join(f'{losses.get(k, 0):^10.2e}'
                                    for k in loss_components)
            else:
                loss_str = ''
        """     
    else:
        if epoch:
            preambule = f'{epoch:{Kep}d}/{epochs:<{Kep}d} {preambule:>5} '
        else:
            preambule = f'{preambule:>{5 + 2 * Kep + 2}} '
        if loss_components:

            if no_loss:
                loss_str = '|'.join(Kn * ' ' for k in loss_components)
            else:
                formatted = {k: num_format.get(k, num_format['default'])
                             for k in loss_components}
                value = {k: losses.get(k, np.nan)
                         for k in loss_components}
            
                loss_str = '|'.join(formatted[k].format(value[k])
                                    for k in loss_components)
        else: loss_str = ''
        if metrics:
            if no_metrics:
                metrics_str = '|'.join(Kn * ' ' for k in metrics)
            else:
                formatted = {k: num_format.get(k, num_format['default'])
                         for k in metrics}
                value = {k: measures.get(k, np.nan)
                         for k in metrics}
            
                metrics_str = '|'.join(formatted[k].format(value[k])
                                       for k in metrics)
            
        else: metrics_str = ''

    if epoch == -2:
        length = len('|'.join(f'{k:^9}' for k in acc_methods)) 
        acc_str = f'{"accuracy":_^{length}}'
    elif epoch == -1: 
        acc_str = '|'.join(f'{k:^9}' for k in acc_methods)
    elif accuracies:
        acc_str_ = []
        for k in acc_methods:
            acc_str_.append(f' {accuracies[k]:7.2%} ')
        acc_str = '|'.join(acc_str_)
    else:
        acc_str = '|'.join(9 * ' ' for k in acc_methods)
        
    if time_per_i > 0:
        time_per_i = Time(time_per_i)
        if i < per_epoch - 1:
            eta_str = f' {time_per_i / batch_size:>9}/i'
            eta_str += f'   eta: {time_per_i * (per_epoch - i):<9}'
        else:
            eta_str = f' {time_per_i / batch_size:>9}/i'
            eta_str += f' total: {time_per_i * per_epoch:<9}'
       
    else:
        eta_str = ' '

    strings = [s for s in [preambule,
                           loss_str,
                           metrics_str,
                           acc_str,
                           eta_str] if s]
    
    print('\r' + '||'.join(strings),
          end_esc,
          end='' if i < per_epoch - 1 else end_of_epoch)

    if i == per_epoch - 1:

        with open('train.log', 'a') as f:
            f.write('|'.join(strings + [end_esc]) + '\n')

def debug_nan(value, inspected, name):

    if torch.isnan(value).any():
        for i in inspected:
            logging.error('%s : %s', name, torch.isnan(i).any().item())
        raise ValueError(name)
            
def progress_bar(i, per_epoch, width=20):

    N = width ** 2

    step = round(i * N / per_epoch)

    lss = step % width
    mss = step // width 

    n_both = min(mss, lss)
    n_mss = max(mss -  lss, 0)
    n_lss = max(lss - mss, 0)
    n_blk = width - n_both - n_mss - n_lss
    str = 'ø' * n_both
    str += 'o' * n_mss
    str += '/' * n_lss
    str += n_blk * ' ' 

    return str

    print(str)
    return step, mss, lss


class Time(float):

    def __str__(self, max=2):

        t = self
        i = 0

        if t == 0:
            return '0s'
        
        str = '-' if t < 0 else ''
        t = abs(t)
        
        d = int(t / (24 * 60 * 60))
        if d > 0:
            str += f'{d}d'
            i += 1
            t -= d * 24 * 60 * 60

        h = int(t / 3600)
        if h > 0:
            str += f'{h}h'
            i +=1
            t -= h * 3600

        m = int(t / 60)
        if m > 0 and i < max:
            str += f'{m}m'
            i += 1
            t -= m * 60

        s = int(t)
        if s > 0 and i < max:
            str += f'{s}s'
            i += 1
            t -= s

        m = int(1e3 * t)
        mu = int(1e6 * t - 1000 * m)
        
        if i < max - 1 and mu > 0:
            if m > 0:
                str += f'{m}ms{mu:03d}'
            else:
                str += f'{mu}us'
                
        elif i < max and m > 0:
            str += f'{m}ms'

        return str
        
    def __add__(self, t_):

        return Time(float(self) + float(t_))

    def __neg__(self):

        return Time(-float(self))
        
    def __sub__(self, t):

        return self + (-t)

    def __mul__(self, k):

        return Time(float(self) * k)

    def __truediv__(self, k):

        return Time(float(self) / k)
    
    def __format__(self, *a, **k):

        return str(self).__format__(*a, **k)

    
if __name__ == '__main__':
        
    epochs = 10
    per_epoch = 60

    print_epoch(per_epoch-1, per_epoch, -1, epochs, 0)

    for epoch in range(epochs):
        for i in range(per_epoch):

            l = np.random.randn()
            time.sleep(5)
            print_epoch(i, per_epoch, epoch, epochs, l, end_of_epoch='')


    
