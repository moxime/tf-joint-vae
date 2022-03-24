import os
import json
import logging
import pandas as pd
import hashlib
import utils.torch_load as torchdl
import numpy as np
import random
import torch
from module.optimizers import Optimizer
import re
from utils.misc import make_list
from utils.torch_load import get_same_size_by_name, get_shape_by_name
from utils.roc_curves import fpr_at_tpr
from contextlib import contextmanager
import functools
from utils.print_log import turnoff_debug
from utils.filters import get_filter_keys

class NoModelError(Exception):
    pass
class DeletedModelError(NoModelError):
    pass

def iterable_over_subdirs(arg, iterate_over_subdirs=False, keep_none=False, iterate_over_subdirs_if_found=False):
    def iterate_over_subdirs_wrapper(func):
        @functools.wraps(func)
        def iterated_func(*a, keep_none=keep_none, **kw):
            if isinstance(arg, str):
                directory = kw.get(arg)
            else:
                directory = a[arg]
            # print('***', directory[-10:], 'a:', *a, 'k:', *kw, '***')  
            out = func(*a, **kw)
        
            if out is not None or keep_none:
                yield out
            try:
                rel_paths = os.listdir(directory)
                paths = [os.path.join(directory, p) for p in rel_paths]
                dirs = [d for d in paths if os.path.isdir(d)]
            except PermissionError:
                dirs = []
            if out is None or iterate_over_subdirs_if_found:
                for d in dirs:
                    if isinstance(arg, str):
                        kw[arg] = d
                    else:
                        a = list(a)
                        a[arg] = d
                    yield from iterated_func(*a, **kw)

        @functools.wraps(func)
        def wrapped_func(*a, iterate_over_subdirs=iterate_over_subdirs, **kw):

            if not iterate_over_subdirs:
                try:
                    return next(iter(iterated_func(*a, keep_none=True, **kw)))
                except StopIteration:
                    return
            if iterate_over_subdirs == True:
                return iterated_func(*a, **kw)
            else:
                return iterate_over_subdirs(iterated_func(*a, **kw))
        return wrapped_func

    return iterate_over_subdirs_wrapper


def get_path(dir_name, file_name, create_dir=True):

    dir_path = os.path.realpath(dir_name)
    if not os.path.exists(dir_path) and create_dir:
        os.makedirs(dir_path)

    return os.path.join(dir_name, file_name)


def job_to_str(number, string, formats={int: '{:06d}'}):
    job_format = formats.get(type(number), '{}')
    return string.replace('%j', job_format.format(number))


def create_file_for_job(number, directory, filename, mode='w'):

    directory = job_to_str(number, directory)

    if not os.path.exists(directory):
        os.makedirs(directory)
    filepath = os.path.join(directory, filename)
    
    return open(filepath, mode)


def save_json(d, dir_name, file_name, create_dir=True):

    p = get_path(dir_name, file_name, create_dir)

    with open(p, 'w') as f:
        json.dump(d, f)


def load_json(dir_name, file_name, presumed_type=str):

    p = get_path(dir_name, file_name, create_dir=False)

    # logging.debug('*** %s', p)
    with open(p, 'rb') as f:
        try:
            d = json.load(f)
        except json.JSONDecodeError:
            logging.error('Corrupted file\n%s', p)
            return {}
    d_ = {}
    for k in d:
        try:
            k_ = presumed_type(k)
        except ValueError:
            k_ = k
        d_[k_] = d[k]

    return d_


def shorten_path(path, max_length=30):

    if len(path) > max_length:
        return (path[:max_length // 2 - 2] +
                '...' + path[-max_length // 2 + 2:])

    return path

    
def get_path_from_input(dir_path=os.getcwd(), count_nets=True):

    rel_paths = os.listdir(dir_path)
    abs_paths = [os.path.join(dir_path, d) for d in rel_paths]
    sub_dirs_rel_paths = [rel_paths[i] for i, d in enumerate(abs_paths) if os.path.isdir(d)]
    print(f'<enter>: choose {dir_path}', end='')
    if count_nets:
        list_of_nets = collect_models(dir_path, load_net=False)
        num_of_nets = len(list_of_nets)
        print(f' ({num_of_nets} networks)')
    else:
        print()

    for i, d in enumerate(sub_dirs_rel_paths):
        print(f'{i+1:2d}: enter {d}', end='')
        if count_nets:
            list_of_nets = collect_models(os.path.join(dir_path, d), load_net=False)
            num_of_nets = len(list_of_nets)
            print(f' ({num_of_nets} networks)')
        else:
            print()

    print(' p: return to ..')
    input_string = input('Your choice: ')
    try:
        i = int(input_string)
        is_int = True
    except ValueError:
        i = input_string
        is_int = False

    if is_int:
        if 0 < i < len(sub_dirs_rel_paths) + 1:
            return get_path_from_input(dir_path=os.path.join(dir_path,
                                                             sub_dirs_rel_paths[i-1]))
        else:
            return get_path_from_input(dir_path)
    elif i == '':
        return dir_path
    elif i == 'p':
        path = os.path.join(dir_path, os.pardir)
        path = os.path.abspath(path)
        return get_path_from_input(path)
    else:
        return get_path_from_input(dir_path)


def model_directory(model, *subdirs):

    if isinstance(model, str):
        directory = model

    elif isinstance(model, dict):
        directory = model['dir']

    else:
        directory = model.saved_dir

    return os.path.join(directory, *subdirs)

        
class ObjFromDict:

    def __init__(self, d, **defaults):
        for k, v in defaults.items():
            setattr(self, k, v)
        for k, v in d.items():
            setattr(self, k, v)

            
def print_architecture(o, sigma=False, sampling=False,
                       excludes=[], short=False):

    arch = ObjFromDict(o.architecture, features=None)
    training = ObjFromDict(o.training_parameters)
    
    def _l2s(l, c='-', empty='.'):
        if l:
            return c.join(str(_) for _ in l)
        return empty

    def s_(s):
        return s[0] if short else s

    if arch.features:
        features = arch.features['name']
    s = ''
    if 'type' not in excludes:

        s += s_('type') + f'={arch.type}--'
    if 'activation' not in excludes:
        if arch.type != 'vib':
            s += s_('output') + f'={arch.output}--'
        s += s_('activation') + f'={arch.activation}--'
    if 'latent_dim' not in excludes:
        s += s_('latent-dim') + f'={arch.latent_dim}--'
    # if sampling:
    #    s += f'sampling={self.latent_sampling}--'
    if arch.features:
        s += s_('features') + f'={features}--'
    if 'batch_norm' not in excludes:
        w = '-' + arch.batch_norm if arch.batch_norm else ''
        s += f'batch-norm{w}--' if arch. batch_norm else ''

    s += s_('encoder') + f'={_l2s(arch.encoder)}--'
    if 'decoder' not in excludes:
        s += s_('decoder') + f'={_l2s(arch.decoder)}--'
        if arch.upsampler:
            s += s_('upsampler') + f'={_l2s(arch.upsampler)}--'
    s += s_('classifier') + f'={_l2s(arch.classifier)}--'

    s += s_('variance') + f'={arch.latent_prior_variance:.1f}'
    
    if sigma and 'sigma' not in excludes:
        s += '--' + s_('sigma') + f'={o.sigma}'
    
    if sampling and 'sampling' not in excludes:
        s += '--'
        s += s_('sampling')
        s += f'={training.latent_sampling}'

    return s


def option_vector(o, empty=' ', space=' '): 

    arch = ObjFromDict(o.architecture, features=None)
    training = ObjFromDict(o.training_parameters, transformer='default')
    v_ = []
    if arch.features:
        w = ''
        w += 'p:'
        if training.pretrained_features:
            w+= 'f'
        else:
            w+= empty

        if arch.upsampler:
            if training.pretrained_upsampler:
                w += 'u'
            else:
                w += empty
        v_.append(w)

    w = 't:' + training.transformer[0]
    v_.append(w)

    w = 'bn:'
    if not arch.batch_norm:
        c = empty
    else:
        # print('****', self.batch_norm)
        c = arch.batch_norm[0]
    w += c
    v_.append(w)

    w = 'a:'
    for m in ('flip', 'crop'):
        if m in training.data_augmentation:
            w += m[0]
        else: w += empty
    v_.append(w)

    w = 'w:'
    if training.warmup:
        w += f'{training.warmup:02d}'
    else:
        w += 2 * empty
    v_.append(w)

    if arch.type == 'cvae':
        w = 'c:'
        w += {'random': 'r', 'learned':'l', 'onehot':'1'}[training.coder_means]
        v_.append(w)

    return space.join(v_)


class Shell:

    print_architecture = print_architecture
    option_vector = option_vector

    
class LossRecorder:

    def __init__(self,
                 batch_size,
                 num_batch=0,
                 device=None,
                 **tensors):

        self.last_batch_size = {}
        self.reset()

        self._num_batch = 0
        self._samples = 0
        
        self.batch_size = batch_size

        self._tensors = {}

        self.device = device

        if tensors:
            self._create_tensors(num_batch, device=device, **tensors)
            
    def _create_tensors(self, num_batch, device=None, **tensors):

        assert not self._tensors
        self._num_batch = num_batch
        self._samples = num_batch * self.batch_size
        
        if not device and not self.device:
            device = next(iter(tensors.values())).device

        self.device = device

        for k, t in tensors.items():
            shape = t.shape[:-1] + (self._samples,)
            self._tensors[k] = torch.zeros(shape,
                                           dtype=t.dtype,
                                           device=self.device)
            self.last_batch_size[k] = self.batch_size

    def to(self, device):

        for t in self._tensors:
            self._tensors[t] = self._tensors[t].to(device)

    def reset(self):

        self._recorded_batches = 0
        self._seed = np.random.randint(1, int(1e8))
        self.last_batch_size = {k: self.batch_size for k in self.last_batch_size}
        return

    def init_seed_for_dataloader(self):

        self._initial_seed = torch.seed() 
        seed = self._seed
        torch.manual_seed(seed)
        
    def restore_seed(self):
        torch.manual_seed(self._initial_seed)
            
    def keys(self):
        return self._tensors.keys()
    
    def __len__(self):
        return self._recorded_batches

    def __repr__(self):
        return ('Recorder for '
                + ' '.join([str(k) for k in self.keys()]))

    def save(self, file_path, cut=True):

        """dict_ = self.__dict__.copy()
        tensors = dict.pop('_tensors')
        """

        if cut:
            self.num_batch = len(self)
            t = self._tensors
            for k in t:
                end = (self.num_batch - 1) * self.batch_size + self.last_batch_size[k]
                t[k] = t[k][..., 0:end]

        torch.save(self.__dict__, file_path)

    @classmethod
    def load(cls, file_path, device=None, **kw):

        if 'map_location' not in kw and not torch.cuda.is_available():
            kw['map_location'] = torch.device('cpu')
        dict_of_params = torch.load(file_path, **kw)
        num_batch = dict_of_params['_num_batch']
        batch_size = dict_of_params['batch_size']
        tensors = dict_of_params['_tensors']
        
        r = LossRecorder(batch_size, num_batch, **tensors)

        for k in ('_seed', '_tensors', '_recorded_batches'):
            setattr(r, k, dict_of_params[k])

        for k in dict_of_params:
            if not k.startswith('_'):
                setattr(r, k, dict_of_params[k])

        if device:
            for k in r._tensors:
                if r._tensors[k].device != device:
                    r._tensors[k] =  r._tensors[k].to('cpu')
        return r

    @classmethod
    def loadall(cls, dir_path, *w, file_name='record-{w}.pth', output='recorders', **kw):
        r"""
        If w is empty will find all recorders in directory
        if output is 'recorders' return recorders, if 'paths' return full paths

        """

        outputs = lambda p: LossRecorder.load(path, **kw) if output.startswith('record') else p
        
        r = {}

        if not w:

            pattern = file_name.replace('.', '\.')
            pattern = pattern.replace('{w}', '(?P<name>.+)')

            for f in os.listdir(dir_path):
                regexp_match = re.match(pattern, f)
                if regexp_match:
                    path = os.path.join(dir_path, f)
                    r[regexp_match.group('name')] = outputs(path)
                
        for word in w:
            f = file_name.format(w=word)
            path = os.path.join(dir_path, f)
            if os.path.exists(path):
                r[word] = outputs(path)
            else:
                logging.warning(f'{f} not found')
                
        return r
    
    @property
    def num_batch(self):
        return self._num_batch
    
    @num_batch.setter
    def num_batch(self, n):

        if not self._tensors:
            return
        
        first_tensor = next(iter(self._tensors.values()))
        height = first_tensor.shape[-1]
        n_sample = n * self.batch_size
        
        if n_sample > height:
            d_h = n_sample - height
            for k in self._tensors:

                t = self._tensors[k]
                # print('sl353:', 'rec', self.device, k, t.device)
                z = torch.zeros(t.shape[:-1] + (d_h,),
                                dtype=t.dtype,
                                device=self.device)
                self._tensors[k] = torch.cat([t, z], axis=-1)
                    
        self._num_batch = n
        self._samples = n * self.batch_size
        self._recorded_batches = min(n, self._recorded_batches)
                
    def has_batch(self, number):
        r""" number starts at 0
        """

        return number < self._recorded_batches
    
    def get_batch(self, i, *which):
        
        if not which:
            return self.get_batch(i, *self.keys())
            
        if len(which) > 1:
            return {w: self.get_batch(i, w) for w in which}

        if not self.has_batch(i):
            raise IndexError(f'{i} >= {len(self)}')
        
        start = i * self.batch_size
        
        w = which[0]
        if i == len(self) - 1:
            end = start + self.last_batch_size[w]
        else:
            end = start + self.batch_size

        t = self._tensors[w]
        
        return t[..., start:end]
    
    def append_batch(self, extend=True, **tensors):

        if not self._tensors:
            self._create_tensors(1, **tensors)
            
        start = self._recorded_batches * self.batch_size
        end = start + self.batch_size

        if end > self._samples:
            if extend:
                self.num_batch *= 2
            else:
                raise IndexError
        
        for k in tensors:
            if k not in self.keys():
                raise KeyError(k)
            # print('sl:426', 'rec', k, *tensors[k].shape)  #
            batch_size = tensors[k].shape[-1]
            if batch_size < self.batch_size:
                assert self.last_batch_size[k] == self.batch_size
                self.last_batch_size[k] = tensors[k].shape[-1]
                end = start + batch_size
            self.last_batch_size[k] = batch_size
            self._tensors[k][..., start:end] = tensors[k]
                                                    
        self._recorded_batches += 1


def last_samples(model):

    directory = model_directory(model, 'samples')
    
    samples = [int(d) for d in os.listdir(directory) if d.isnumeric()]

    return max(samples)


def average_ood_results(ood_results):

    ood = [s for s in ood_results if not s.endswith('90')]
    
    mean_keys = {'auc': 'val', 'fpr': 'list'}
    min_keys = {'epochs': 'val', 'n': 'val'}
    same_keys = {'tpr', 'thresholds'}

    all_methods = [set(ood_results[s].keys()) for s in ood]
    if all_methods:
        methods = set.intersection(*[set(ood_results[s].keys()) for s in ood])

    else:
        return None
        
    avge_res = {m: {} for m in methods}

    for m in methods:
        for k in mean_keys:
            if mean_keys[k] == 'val':
                vals = [ood_results[s][m][k] for s in ood]
                avge_res[m][k] = np.mean(vals)
            else:
                lists = [ood_results[s][m][k] for s in ood]
                n = min(len(l) for l in lists)
                avge_res[m][k] = [np.mean([l_[i] for l_ in lists]) for i in range(n)]

        for k in min_keys:
            avge_res[m][k] = min(ood_results[s][m][k] for s in ood)

        for k in same_keys:
            avge_res[m][k] = ood_results[ood[0]][m][k]
            
    return avge_res


def clean_results(results, methods, **zeros):

    trimmed = {k: results[k] for k in results if k in methods}
    completed = {k: dict(n=0, epochs=0, **zeros) for k in methods}
    completed.update(trimmed)
    return completed


def develop_starred_methods(methods, methods_params, inplace=True):
    
    if not inplace:
        methods = methods.copy()
    starred_methods = []
    for m in methods:
        if m.endswith('*'):
            methods += methods_params.get(m[:-1], [])
            starred_methods.append(m)

    for m in starred_methods:
        methods.remove(m)
        pass
        
    return methods


def needed_components(*methods):

    total = ('loss', 'logpx', 'sum', 'max', 'mag', 'std', 'mean')
    ncd = {'iws': ('iws',),
           'softiws': ('iws',),
           'closest': ('zdist',),
           'kl': ('kl',),
           'soft': ('kl',),
           'softkl': ('kl',),
           'mse': ('cross_x',)}

    ncd.update({_: (_,) for _ in ('kl', 'fisher_rao', 'mahala')})

    for k in total:
        ncd[k] = ('total',)

    methods_ = []
    for m in methods:
        if m.endswith('-2s'):
            methods_.append(m[:-3])
        elif '-a-' in m:
            methods_.append(m.split('-')[0])
        else:
            methods_.append(m)
    return sum((ncd.get(m, ()) for m in methods_), ())


def available_results(model,
                      testset='trained',
                      min_samples_by_class=200,
                      samples_available_by_class=800,
                      predict_methods='all',
                      misclass_methods='all',
                      oodsets='all',
                      wanted_epoch='last',
                      epoch_tolerance=5,
                      where='all',
                      ood_methods='all'):

    if isinstance(model, dict):
        model = model['net']

    ood_results = model.ood_results
    test_results = model.testing
    if wanted_epoch == 'min-loss':
        wanted_epoch = model.training_parameters.get('early-min-loss', 'last')
    if wanted_epoch == 'last':
        wanted_epoch = max(model.testing)
    predict_methods = make_list(predict_methods, model.predict_methods)
    ood_methods = make_list(ood_methods, model.ood_methods)
    misclass_methods = make_list(misclass_methods, model.misclass_methods)

    anywhere = ('json', 'recorders', 'compute')
    where = make_list(where, anywhere)

    for _l in (predict_methods, ood_methods, misclass_methods):
        develop_starred_methods(_l, model.methods_params)

    if testset == 'trained':    
        testset = model.training_parameters['set']
    # print('***', testset)
    # print('*** testset', testset)
    all_ood_sets = get_same_size_by_name(testset)

    if ood_methods:
        oodsets = make_list(oodsets, all_ood_sets)
    else:
        oodsets = []

    sets = [testset] + oodsets

    min_samples = {}
    samples_available_by_compute = {}
    
    for s in sets:
        C = get_shape_by_name(s)[-1]
        if not C:
            C = model.num_labels
        min_samples[s] = C * min_samples_by_class
        samples_available_by_compute[s] = C * samples_available_by_class

    # print(*min_samples.values())
    # print(*samples_available_by_compute.values())
        
    methods = {testset: [(m,) for m in predict_methods]}
    methods[testset] += [(pm, mm) for mm in misclass_methods for pm in predict_methods]
    methods[testset] += [(m, ) for m in ood_methods]
    methods.update({s: [(m,) for m in ood_methods] for s in oodsets})

    sample_dir = os.path.join(model.saved_dir, 'samples')

    if os.path.isdir(sample_dir):
        sample_sub_dirs = {int(_): _ for _ in os.listdir(sample_dir) if _.isnumeric()}
    else:
        sample_sub_dirs = {}
        
    epochs = set(sample_sub_dirs)
    
    epochs.add(model.trained)
    # print('****', *epochs, '/', *test_results, '/', *ood_results)
    epochs = sorted(set.union(epochs, set(test_results), set(ood_results)))

    if wanted_epoch:
        epochs = [_ for _ in epochs if abs(_ - wanted_epoch) <= epoch_tolerance]
    
    test_results = {_: clean_results(test_results.get(_, {}), predict_methods) for _ in epochs} 

    results = {}

    for e in sorted(epochs):
        pm_ = list(test_results[e].keys())
        results[e] = {s: clean_results(ood_results.get(e, {}).get(s, {}), ood_methods) for s in sets}
        for pm in pm_:
            misclass_results = clean_results(test_results[e][pm], misclass_methods)
            test_results[e].update({pm + '-' + m: misclass_results[m] for m in misclass_results})
        results[e][testset].update({m: test_results[e][m] for m in test_results[e]})
    
    available = {e: {s: {'json': {m: results[e][s][m]['n']
                                  for m in results[e][s]}}
                     for s in results[e]}
                 for e in results}
                 
    # print(available['json'])

    for e in available:
        for s in available[e]:
            for w in ('recorders', 'compute'):
                available[e][s][w] = {'-'.join(m): 0 for m in methods[s]} 

    for epoch in results:
        rec_dir = os.path.join(sample_dir, sample_sub_dirs.get(epoch, 'false_dir'))
        if os.path.isdir(rec_dir):
            recorders = LossRecorder.loadall(rec_dir)
            # epoch = last_samples(model)
            for s, r in recorders.items():
                # print('***', s)
                if s not in sets:
                    continue
                n = len(r) * r.batch_size
                for m in methods[s]:
                    all_components = all(c in r.keys() for c in needed_components(*m))
                    if all_components:
                        available[epoch][s]['recorders']['-'.join(m)] = n
                        available[epoch]['rec_dir'] = rec_dir

    if abs(wanted_epoch - model.trained) <= epoch_tolerance:
        for s in sets:
            for m in methods[s]:
                available[model.trained][s]['compute']['-'.join(m)] = samples_available_by_compute[s]

    # return available

    wheres = [w for w in ['compute', 'recorders', 'json'] if w in where]
    wheres.append('zeros')
    for epoch in available:
        for dset in sets:
            a_ = available[epoch][dset]
            a_['where'] = {w: 0 for w in anywhere}
            a_['zeros'] = {'-'.join(m): 0 for m in methods[dset]}
            # print(epoch, dset) # a_['json'])
            for i, w in enumerate(wheres[:-1]):
                gain = {'-'.join(m): 0 for m in methods[dset]}
                others = {'-'.join(m): 0 for m in methods[dset]}
                for m in gain:
                    others[m] = max(a_[_].get(m, 0) for _ in wheres[i+1:])
                    gain[m] += a_[w].get(m, 0) - others[m] > min_samples[dset]
                    # gain[m] *= (gain[m] > 0)
                available[epoch][dset]['where'][w] = sum(gain.values())
            a_.pop('zeros')

    for epoch in available:
        available[epoch]['all_sets'] = {w: sum(available[epoch][s]['where'][w] for s in sets) for w in anywhere}
        available[epoch]['all_sets']['anywhere'] = sum(available[epoch]['all_sets'][w] for w in anywhere)
    return available


def make_dict_from_model(model, directory, tpr=0.95, wanted_epoch='last', **kw):

    architecture = ObjFromDict(model.architecture, features=None)
    training = ObjFromDict(model.training_parameters,
                           transformer='default',
                           max_batch_sizes={'train': 8, 'test': 8},
                           pretrained_upsampler=None)

    logging.debug(f'net found in {shorten_path(directory)}')
    arch =  model.print_architecture(excludes=('latent_dim', 'batch_norm'))
    arch_code = hashlib.sha1(bytes(arch, 'utf-8')).hexdigest()[:6]
    # arch_code = hex(hash(arch))[2:10]
    pretrained_features =  (None if not architecture.features
                            else training.pretrained_features)
    pretrained_upsampler = training.pretrained_upsampler
    batch_size = training.batch_size
    if not batch_size:
        train_batch_size = training.max_batch_sizes['train']
    else:
        train_batch_size = batch_size

    model.testing[-1] = {}
    if wanted_epoch == 'min-loss':
        if 'early-min-loss' in model.training_parameters:
            wanted_epoch = model.training_parameters['early-min-loss']
        else:
            logging.warning('Min loss epoch had not been computed for %s. Will fecth last', model.trained)
            wanted_epoch = 'last'

    if wanted_epoch == 'last':
        wanted_epoch = max(model.testing)
            
    testing_results = clean_results(model.testing.get(wanted_epoch, {}), model.predict_methods, accuracy=0.)
    accuracies = {m: testing_results[m]['accuracy'] for m in testing_results}
    ood_results = model.ood_results.get(wanted_epoch, {}).copy()
    training_set = model.training_parameters['set']

    forced_var = architecture.encoder_forced_variance
    if not forced_var:
        forced_var = None
    
    if training_set in ood_results:
        ood_results.pop(training_set)
    
    if model.testing.get(wanted_epoch) and model.predict_methods:
        # print('*** model.testing', *model.testing.keys())
        # print('*** model.predict_methods', model.architecture['type'], *model.predict_methods)
        accuracies['first'] = accuracies[model.predict_methods[0]] 
        best_accuracy = max(testing_results[m]['accuracy'] for m in testing_results)
        tested_epoch = min(testing_results[m]['epochs'] for m in testing_results)
        n_tested = min(testing_results[m]['n'] for m in testing_results)
    else:
        best_accuracy = accuracies['first'] = None
        tested_epoch = n_tested = 0

    
    parent_set, heldout = torchdl.get_heldout_classes_by_name(training_set)

    if heldout:
        # print('***', *heldout, '***', *model.ood_results)
        matching_ood_sets = [k for k in ood_results if k.startswith(parent_set)]
        if matching_ood_sets:
            ood_results[parent_set + '+?'] = ood_results.pop(matching_ood_sets[0])
        all_ood_sets = [parent_set + '+?']

    else:
        all_ood_sets = torchdl.get_same_size_by_name(training_set)

    heldout = tuple(sorted(heldout))
    
    average_ood = average_ood_results(ood_results)
    if average_ood:
        ood_results['average'] = average_ood
    all_ood_sets.append('average')
    tested_ood_sets = [s for s in ood_results if s in all_ood_sets]

    ood_fprs = {s: {} for s in all_ood_sets}
    ood_fpr = {s: None for s in all_ood_sets}
    best_auc = {s: None for s in all_ood_sets}
    best_method = {s: None for s in all_ood_sets}
    n_ood = {s: 0 for s in all_ood_sets}
    epochs_ood = {s: 0 for s in all_ood_sets}

    for s in tested_ood_sets:
        res_by_set = {}
        ood_results_s = clean_results(ood_results[s], model.ood_methods, fpr=[], tpr=[], auc=None)

        starred_methods = [m for m in ood_results_s if m.endswith('*')]

        _r = ood_results[s]
        for m in starred_methods:
            methods_to_be_maxed = {m_: fpr_at_tpr(_r[m_]['fpr'], _r[m_]['tpr'], tpr)
                                   for m_ in _r if m_.startswith(m[:-1]) and _r[m_]['auc']}
            params_max_auc = min(methods_to_be_maxed, key=methods_to_be_maxed.get, default=None)
            if params_max_auc:
                ood_results_s[m] = _r[params_max_auc]
            ood_results_s[m]['params'] = params_max_auc
            
        for m in ood_results_s:
            fpr_ = ood_results_s[m]['fpr']
            tpr_ = ood_results_s[m]['tpr']
            auc = ood_results_s[m]['auc']
            if auc and (not best_auc[s] or auc > best_auc[s]):
                best_auc[s] = auc
                best_method[s] = m
            res_by_method = {tpr: fpr for tpr, fpr in zip(tpr_, fpr_)}
            res_by_method['auc'] = auc
            res_by_set[m] = res_by_method
        res_by_set['first'] = res_by_set[model.ood_methods[0]]
        ood_fprs[s] = res_by_set
        if best_method[s]:
            ood_fpr[s] = res_by_set[best_method[s]]

        epochs_ood[s] = min(ood_results_s[m]['epochs'] for m in ood_results_s)
        n_ood[s] = min(ood_results_s[m]['n'] for m in ood_results_s)

    history = model.train_history
    if history.get('test_measures', {}):
        mse = model.train_history['test_measures'][-1].get('mse', np.nan)
        rmse = np.sqrt(mse)
    else:
        rmse = np.nan

    nans = {'total': np.nan, 'zdist': np.nan}
    loss_ = {}
    for s in ('train', 'test'):
        last_loss = ([nans] + history.get(s + '_loss', [nans]))[-1]
        loss_[s] = nans.copy()
        loss_[s].update(last_loss)

    has_validation = 'validation_loss' in history
    
    sigma = model.sigma
    beta = model.training_parameters['beta']
    if sigma.learned and not sigma.coded:
        sigma_train = 'learned'
        beta_sigma = sigma.value * np.sqrt(beta)
    elif sigma.coded:
        sigma_train = 'coded'
        beta_sigma = sigma.value * np.sqrt(beta)        
    elif sigma.is_rmse:
        sigma_train = 'rmse'
        beta_sigma = rmse * np.sqrt(beta)
    elif sigma.decay:
        sigma_train = 'decay'
        beta_sigma = rmse * np.sqrt(beta)
    else:
        sigma_train = 'constant'
        beta_sigma = sigma.value

    sigma_size = 'S' if sigma.sdim == 1 else 'M' 
        
    if architecture.type == 'cvae':
        coder_dict = model.training_parameters['coder_means']
        if coder_dict == 'learned':
            if history['train_measures']:
                # print('sl:366', rmse, *history.keys(), *[v for v in history.values()])
                dict_var = history['train_measures'][-1]['ld-norm']
            else:
                dict_var = model.training_parameters['dictionary_variance']
        else:
            dict_var = model.training_parameters['dictionary_variance']
    else:
        coder_dict = None
        dict_var = 0.

    empty_optimizer = Optimizer([torch.nn.Parameter()], **training.optim)
    depth = (1 + len(architecture.encoder)
             + len(architecture.decoder))
             # + len(architecture.classifier))

    width = (architecture.latent_dim +
             sum(architecture.encoder) +
             sum(architecture.decoder) +
             sum(architecture.classifier)) 

    # print('TBR', architecture.type, model.job_number, *loss_['test'].keys())

    rec_dir = os.path.join(directory, 'samples', 'last')
    if os.path.exists(rec_dir):
        recorders = LossRecorder.loadall(rec_dir,
                                         output='paths')
    else:
        recorders = {}
    if recorders:
        recorded_epoch = last_samples(directory)
    else:
        recorded_epoch = None

    return {'net': model,
            'job': model.job_number,
            'is_resumed': model.is_resumed,
            'type': architecture.type,
            'arch': arch,
            'dict_var': dict_var,
            'coder_dict': coder_dict,
            'forced_var': forced_var,
            'gamma': model.training_parameters['gamma'],
            'arch_code': arch_code,
            'features': architecture.features['name'] if architecture.features else 'none',
            'dir': directory,
            'heldout': heldout,  # tuple(sorted(heldout)),
            'h/o': ','.join(str(_) for _ in heldout),
            'set': parent_set + ('-?' if heldout else ''),
            # 'parent_set': parent_set,
            'data_augmentation': training.data_augmentation,
            'train_batch_size': train_batch_size,
            'sigma': sigma.value if sigma_train == 'constant' else np.nan,
            'beta_sigma': beta_sigma,
            'sigma_train': sigma_train,  #[:5],
            'beta': beta,
            'done': model.train_history['epochs'],
            'epochs': model.training_parameters['epochs'],
            'has_validation': has_validation,
            'trained': model.train_history['epochs'] / model.training_parameters['epochs'],
            'finished': model.train_history['epochs'] >= model.training_parameters['epochs'],
            'n_tested': n_tested,
            'epoch': tested_epoch,
            'accuracies': accuracies,
            'best_accuracy': best_accuracy,
            'n_ood': n_ood,
            'ood_fprs': ood_fprs,
            'ood_fpr': ood_fpr,
            'recorders': recorders,
            'recorded_epoch': recorded_epoch,
            'rmse': rmse,
            'test_loss': loss_['test']['total'],
            'train_loss': loss_['train']['total'],
            'test_zdist': np.sqrt(loss_['test']['zdist']),
            'train_zdist': np.sqrt(loss_['train']['zdist']),
            'K': architecture.latent_dim,
            'L': training.latent_sampling,
            'warmup': training.warmup,
            'pretrained_features': str(pretrained_features),
            'pretrained_upsampler': str(pretrained_upsampler),
            'batch_norm': architecture.batch_norm,
            'depth': depth,
            'width': width,
            'options': model.option_vector(),
            'optim_str': f'{empty_optimizer:3}',
            'optim': empty_optimizer.kind,
            'lr': empty_optimizer.init_lr,
    }


def register_models(models, *keys):
    d = {}
    for m in models:
        d[m['dir']] = {_: m[_] for _ in keys}

    return d


def fetch_models(search_dir, registered_models_file, filter=None, flash=True, load_net=False, **kw):

    if flash:
        logging.debug('Flash collecting networks')
        try:
            rmodels = load_json(search_dir, registered_models_file)
            with turnoff_debug():
                return gather_registered_models(rmodels, filter, load_net=load_net, **kw)
                
        except (FileNotFoundError, NoModelError) as e:
            logging.warning('%s not found, will recollect networks', e)
            flash = False
            
    if not flash:    
        logging.debug('Collecting networks')
        with turnoff_debug():
            list_of_networks = collect_models(search_dir,
                                              load_net=False,
                                              **kw)
        filter_keys = get_filter_keys()
        rmodels = register_models(list_of_networks, *filter_keys)
        save_json(rmodels, search_dir, registered_models_file)
        return fetch_models(search_dir, registered_models_file, filter=filter, flash=True,
                             load_net=load_net, **kw)


def gather_registered_models(mdict, filter, tpr_for_max=0.95, wanted_epoch='last', **kw):

    from cvae import ClassificationVariationalNetwork

    mlist = []
    for _ in mdict:
        if filter is None or filter.filter(mdict[_]):
            m = ClassificationVariationalNetwork.load(_, **kw)
            mlist.append(make_dict_from_model(m, _, tpr=tpr_for_max, wanted_epoch=wanted_epoch))

    return mlist

                         
@iterable_over_subdirs(0, iterate_over_subdirs=list)
def collect_models(directory,
                     wanted_epoch='last',
                     load_state=True, tpr_for_max=0.95, **default_load_paramaters):

    from cvae import ClassificationVariationalNetwork

    if 'dump' in directory:
        return

    assert wanted_epoch == 'last' or not load_state
    
    try:
        logging.debug(f'Loading net in: {directory}')
        model = ClassificationVariationalNetwork.load(directory,
                                                      load_state=load_state,
                                                      **default_load_paramaters)

        return make_dict_from_model(model, directory, tpr=tpr_for_max, wanted_epoch=wanted_epoch) 

    except (FileNotFoundError, PermissionError, NoModelError) as e:    
        pass

    except RuntimeError as e:
        logging.warning(f'Load error in {directory} see log file')
        logging.debug(f'Load error: {e}')
    

def is_derailed(model, load_model_for_check=False):
    from cvae import ClassificationVariationalNetwork

    if isinstance(model, dict):
        directory = model['dir']

    elif isinstance(model, str):
        directory = model

    else:
        directory = model.saved_dir

    if os.path.exists(os.path.join(directory, 'derailed')):
        return True
    
    elif load_model_for_check:
        try:
            model = ClassificationVariationalNetwork.load(directory)
            if torch.cuda.is_available():
                model.to('cuda')
            x = torch.zeros(1, *model.input_shape, device=model.device)
            model.evaluate(x)
        except ValueError:
            return True

    return False            


def find_by_job_number(*job_numbers, job_dir='jobs', tpr_for_max=0.95, load_net=True, force_dict=False, **kw):

    from cvae import ClassificationVariationalNetwork
    d = {}

    job_numbers_list = list(job_numbers)
    models = collect_models(job_dir,
                              tpr_for_max=tpr_for_max,
                              load_net=False,
                              iterate_over_subdirs=True,
                              **kw)
    for m in models:
        n = m['job']
        if n in job_numbers_list:
            d[n] = m
            job_numbers_list.remove(n)
            if load_net:
                d[n]['net'] = ClassificationVariationalNetwork.load(m['dir'], **kw)
        if not job_numbers_list:
            break
        
    return d if len(job_numbers) > 1 or force_dict else d[job_numbers[0]]


def test_results_df(nets,
                    predict_methods='first',
                    ood_methods='first',
                    ood={},
                    dataset=None, show_measures=True,
                    tpr=[0.95], tnr=False, sorting_keys=[]):
    """
    nets : list of dicts n
    n['net'] : the network
    n['sigma']
    n['arch']
    n['set']
    n['K']
    n['L']
    n['accuracies'] : {m: acc for m in methods}
    n['best_accuracy'] : best accuracy
    n['ood_fpr'] : '{s: {tpr : fpr}}' for best method
    n['ood_fprs'] : '{s: {m: {tpr: fpr} for m in methods}}
    n['options'] : vector of options
    n['optim_str'] : optimizer
    """

    if ood_methods is None:
        ood_methods = 'first'

    if predict_methods is None:
        predict_methods = 'first'
    
    if not dataset:
        testsets = {n['set'] for n in nets}
        return {s: test_results_df(nets,
                                   predict_methods=predict_methods,
                                   ood_methods=ood_methods,
                                   ood=ood.get(s),
                                   dataset=s,
                                   show_measures=show_measures,
                                   tpr=tpr, tnr=tnr,
                                   sorting_keys=sorting_keys) for s in testsets}

    arch_index = ['h/o']  if dataset.endswith('-?') else []
    arch_index += ['type',
                   'depth',
                   'features',
                   'arch_code',
                   'K',
                   # 'dict_var',
                   ]

    train_index = [
        'options',
        'batch_norm',
        'optim_str',
        'coder_dict',
        'forced_var',
        'L',
        'sigma_train',
        'sigma',
        # 'beta_sigma',
        'beta',
        'gamma',
        'job']

    indices = arch_index + train_index

    indices_replacement = {'batch_norm': 'bn'}

    # acc_cols = ['best_accuracy', 'accuracies']
    # ood_cols = ['ood_fpr', 'ood_fprs']

    acc_cols = ['accuracies']
    ood_cols = ['ood_fprs']

    meas_cols = ['epoch', 'done']

    if show_measures > 1:
        meas_cols += ['dict_var', 'beta_sigma', 'rmse',
                      'train_loss', 'test_loss',
                      'train_zdist', 'test_zdist']

    columns = indices + acc_cols + ood_cols + meas_cols
    df = pd.DataFrame.from_records([n for n in nets if n['set'] == dataset],
                                   columns=columns)

    df['batch_norm'] = df['batch_norm'].apply(lambda x: x[0] if x else x)
    df.rename(columns=indices_replacement, inplace=True)

    indices = [indices_replacement.get(_, _) for _ in indices]
    
    df.set_index(indices, inplace=True)
    
    acc_df = pd.DataFrame(df['accuracies'].values.tolist(), index=df.index)
    acc_df.columns = pd.MultiIndex.from_product([acc_df.columns, ['rate']])
    ood_df = pd.DataFrame(df['ood_fprs'].values.tolist(), index=df.index)
    meas_df = df[meas_cols]
    # print(meas_df.columns)
    meas_df.columns = pd.MultiIndex.from_product([[''], meas_df.columns])
    
    # return acc_df
    # return ood_df
    d_ = {dataset: acc_df}

    # print('*** ood_df:', *ood_df, 'ood', ood)
    if ood is not None:
        ood_df = {s: ood_df[s] for s in ood}
    for s in ood_df:
        d_s = pd.DataFrame(ood_df[s].values.tolist(), index=df.index)
        d_s_ = {}
        for m in d_s:
            v_ = d_s[m].values.tolist()
            _v = []
            for v in v_:
                if type(v) is dict:
                    _v.append(v)
                else: _v.append({})
            d_s_[m] = pd.DataFrame(_v, index=df.index)
        if d_s_:
            d_[s] = pd.concat(d_s_, axis=1)
            # print(d_[s].columns)
            # print('==')

            if tnr:
                cols_fpr = d_[s].columns[~d_[s].columns.isin(['auc'], level=-1)]
                d_[s][cols_fpr] = d_[s][cols_fpr].transform(lambda x: 1 - x)

        #d_[s] = pd.DataFrame(d_s.values.tolist(), index=df.index)

    for s in d_:
        show = predict_methods if s == dataset else ood_methods
        cols = d_[s].columns
        kept_columns = cols.isin(tpr + ['rate', 'auc'] + [str(_) for _ in tpr], level=1)
        first_method_columns = cols.isin(['first'], level=0)
        # print('*** 1st', *first_method_columns)

        if show == 'first':
            shown_columns = first_method_columns
        elif show == 'all':
            shown_columns = ~first_method_columns
        else:
            # print(show)
            if isinstance(show, str):
                show = [show]
            shown_columns = cols.isin(show, level=0)

        # print('*** kept', s, *shown_columns, '\n', *d_[s].columns)
        d_[s] = d_[s][cols[shown_columns * kept_columns]]
            
    if show_measures:
        d_['measures'] = meas_df

    df = pd.concat(d_, axis=1)

    df.columns.rename(['set', 'method', 'metrics'], inplace=True)
    
    cols = df.columns

    if False:
        df.columns = df.columns.droplevel(1)

    def _f(x, type='pc'):
        if type == 'pc':
            return 100 * x
        elif type == 'tuple':
            return '-'.join(str(_) for _ in x)
        return x
        
    col_format = {c: _f for c in df.columns}
    for c in df.columns[df.columns.isin(['measures'], level=0)]:
        col_format[c] = lambda x: _f(x, 'measures')

    index_format = {}
    index_format['heldout'] = lambda x: 'H' # _f(x, 'tuple')
    
    sorting_index = []

    if sorting_keys:
        sorting_keys_ = [k.replace('-', '_') for k in sorting_keys]
        for k in sorting_keys_:
            if k in df.index.names:
                sorting_index.append(k)
                continue
            str_k_ = k.split('_')
            k_ = []
            for s_ in str_k_:
                try:
                    k_.append(float(s_))
                except ValueError:
                    k_.append(s_)
            tuple_k = (k_[0], '_'.join([str(_) for _ in k_[1:]]))
            if tuple_k in df.columns:
                sorting_index.append(tuple_k)
                continue
            tuple_k = ('_'.join([str(_) for _ in k_[:-1]]), k_[-1])
            if tuple_k in df.columns:
                sorting_index.append(tuple_k)
                continue

            logging.error(f'Key {k} not used for sorting')
            logging.error('Possible index keys: %s', '--'.join([_.replace('_', '-') for _ in df.index.names]))
            logging.error('Possible columns %s', '--'.join(['-'.join(str(k) for k in c) for c in df.columns]))

    if sorting_index:
        df = df.sort_values(sorting_index)

    return df.apply(col_format)


def needed_remote_files(*mdirs, epoch='last', which_rec='all', state=False):
    r""" list missing recorders to be fetched on a remote

    -- mdirs: list of directories

    -- epoch: last or min-loss or int

    -- which_rec: either 'none' 'ind' or 'all'

    -- state: wehter to include state.pth

    returns generator of needed files paths

    """

    assert not state or epoch == 'last'
    
    from cvae import ClassificationVariationalNetwork as M

    for d in mdirs:

        m = M.load(d, load_net=False)
        epoch_ = epoch
        if epoch_ == 'min-loss':
            epoch_ = m.training_parameters.get('early-min-loss', 'last')
        if epoch_ == 'last':
            epoch_ = max(m.testing)
            
        if isinstance(epoch_, int):
            epoch_ = '{:04d}'.format(epoch_)

        testset = m.training_parameters['set']

        sets = []
        
        if which_rec in ('all', 'ind'):
            sets.append(testset)
            if which_rec == 'all':
                sets += get_same_size_by_name(testset)

        for s in sets:
            sdir = os.path.join(d, 'samples', epoch_, 'record-{}.pth'.format(s))
            if not os.path.exists(sdir):
                yield d, sdir

        if state:
            sdir = os.path.join(d, 'state.pth')
            if not os.path.exists(sdir):
                yield d, sdir

        
    
if __name__ == '__main__':

    dim = {'A': (10,), 'B': (1,), 'I': (3, 32, 32)}
    batch_size = 512
    device = 'cuda'
    
    tensors = {k: torch.randn(*dim[k], 7, device=device) for k in dim}
    
    r = LossRecorder(batch_size)  # , **tensors)    
    r.num_batch = 4
    r.epochs = 10
    
    for _ in range(3):
        r.append_batch(**{k: torch.randn(*dim[k], batch_size) for k in dim})

    r.save('/tmp/r.pth')

    r_ = LossRecorder.load('/tmp/r.pth')
