from __future__ import print_function

from itertools import groupby
import numpy as np
import torch
from cvae import ClassificationVariationalNetwork as CVNet
import data.torch_load as torchdl
import os
import sys
import hashlib
import argparse
import logging

import pandas as pd

from utils.parameters import alphanum, list_of_alphanums, get_args, set_log
from utils.save_load import collect_networks, data_frame_results


def test_accuracy_if(jvae=None,
                     directory=None,
                     testset=None,
                     test_sample_size='all',
                     batch_size=100,
                     unfinished=False,
                     dry_run=False,
                     min_epochs=0,
                     min_test_sample_size=1000,
                     **kw,
):

    assert jvae or directory

    num_batch = test_sample_size
    if type(test_sample_size) is int:
        num_batch = test_sample_size // batch_size
        min_test_sample_size = min(test_sample_size, min_test_sample_size)
    
    if not jvae:
        try:
            jvae = CVNet.load(directory)
        except FileNotFoundError:
            logging.warning(f'Has been asked to load net in {directory}'
                            'none found')

    # deleting old testing methods
    jvae.testing = {m: jvae.testing[m] for m in jvae.predict_methods}
    
    is_trained = jvae.trained >= jvae.training['epochs']
    enough_trained_epochs = jvae.trained >= min_epochs

    min_tested_epochs = min(d['epochs'] for d in jvae.testing.values())
    min_tested_sample_size = min(d['n'] for d in jvae.testing.values())
    enough_samples = min_tested_sample_size >= min_test_sample_size
    enough_tested_epochs = min_tested_epochs >= jvae.trained

    desc = 'in ' + directory if directory else jvae.print_architecture()

    if not is_trained and not unfinished:
        logging.debug(f'Net {desc} not trained, will not be tested')
        return None

    if not enough_trained_epochs:
        logging.debug(f'Net {desc} not trained enough, will not be tested')
        return None
    
    has_been_tested = enough_tested_epochs and enough_samples

    if dry_run:
        return has_been_tested

    if not has_been_tested:

        if not testset:
            _, testset = torchdl.get_dataset(jvae.training['set'],
                                             transformer=jvae.training['transformer'])

        with torch.no_grad():
            jvae.accuracy(testset,
                          batch_size=batch_size,
                          num_batch=num_batch,
                          print_result = 'TEST',
                          **kw)

    return jvae.testing


def test_ood_if(jvae=None,
                directory=None,
                testset=None,
                oodsets=[],
                test_sample_size='all',
                batch_size=100,
                unfinished=False,
                dry_run=False,
                min_epochs=0,
                min_test_sample_size=1000,
                **kw,
                      ):

    assert jvae or directory

    num_batch = test_sample_size
    if type(test_sample_size) is int:
        num_batch = test_sample_size // batch_size
        min_test_sample_size = min(test_sample_size, min_test_sample_size)

    if not jvae:
        try:
            jvae = CVNet.load(directory)
        except FileNotFoundError:
            logging.warning(f'Has been asked to load net in {directory}'
                            'none found')
            return {}

    desc = 'in ' + directory if directory else jvae.print_architecture()

    if not jvae.ood_methods:
        logging.debug(f'Net {desc} has no ood methods')
        return {}
    
    assert jvae.training['set']

    is_trained = jvae.trained >= jvae.training['epochs']
    enough_trained_epochs = jvae.trained >= min_epochs

    if not is_trained and not unfinished:
        logging.debug(f'Net {desc} training not ended, will not be tested')
        return None

    if not enough_trained_epochs:
        logging.debug(f'Net {desc} not trained enough, will not be tested')
        return None

    if testset:
        testset_name = testset.name
    else:
        testset_name = jvae.training['set']

    if oodsets:
        oodset_names = [o.name for o in oodsets]
    else:
        oodset_names = torchdl.get_same_size_by_name(testset_name)
    
    min_tested_epochs = {}
    min_tested_sample_size = {}
    enough_tested_samples = {}
    enough_tested_epochs = {}
    has_been_tested = {}
    zero = {'epochs': 0, 'n': 0}
    zeros = {m: zero for m in jvae.ood_methods}
    oodsets_to_be_tested = []
    
    for n in oodset_names:

        ood_result = jvae.ood_results.get(n, zeros)
        tested_epochs = [ood_result.get(m, zero)['epochs'] for m in jvae.ood_methods]
        min_tested_epochs = min(tested_epochs)
        tested_sample_size = [ood_result.get(m, zero)['n'] for m in jvae.ood_methods]
        min_tested_sample_size = min(tested_sample_size)
        enough_tested_samples = min_tested_sample_size >= min_test_sample_size
        enough_tested_epochs = min_tested_epochs >= jvae.trained
    
        has_been_tested[n] = enough_tested_epochs and enough_tested_samples
        _w = '' if has_been_tested[n] else 'not ' 
        logging.debug(f'ood rate has {_w}been computed with enough samples for {n}')

    if not dry_run:
        transformer = jvae.training['transformer']
        if not testset:
            _, testset = torchdl.get_dataset(testset_name,
                                             transformer=transformer)

        for n in [n for n in has_been_tested if has_been_tested[n]]:
            _, oodset = torchdl.get_dataset(n,
                                            transformer=transformer)
            oodsets_to_be_tested.append(oodset)
            
        _o = ' - '.join([o.name for o in oodsets_to_be_tested])
        logging.debug(f'OOD sets that will be tested: {_o}')
        jvae.ood_detection_rates(oodsets_to_be_tested, testset,
                                 batch_size=batch_size,
                                 num_batch=num_batch,
                                 print_result='*',
                                 **kw)

    else:
        return has_been_tested
    return jvae.ood_results
        
    
if __name__ == '__main__':

    args = get_args('test')
    
    debug = args.debug
    verbose = args.verbose

    log = set_log(verbose, debug, name='test')
    log.debug('$ ' + ' '.join(sys.argv))
    if not args.force_cpu:
        device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        log.info(f'Used device: {device}')
    else:
        device = torch.device('cpu')
        log.info(f'Used device: {device}')
        log.debug(f'CPU asked by user')

    batch_size = args.batch_size
    job_dir = args.job_dir
    load_dir = args.load_dir
    dry_run = args.dry_run
    epochs = args.epochs
    test_sample_size = args.test_sample_size
    ood_sample_size = args.ood
    min_test_sample_size = args.min_test_sample_size
    unfinished_training = args.unfinished

    filters = args.filters
    
    latex_formatting = args.latex
    
    for k in vars(args).items():
        log.debug('%s: %s', *k)
    
    search_dir = load_dir if load_dir else job_dir

    l_o_l_o_d_o_n = []
    collect_networks(search_dir, l_o_l_o_d_o_n, load_state=not dry_run) #, like=dummy_jvae)
    total = sum(map(len, l_o_l_o_d_o_n))
    log.debug(f'{total} networks in {len(l_o_l_o_d_o_n)} lists collected:')

    for (i, l) in enumerate(l_o_l_o_d_o_n):
        a = l[0]['net'].print_architecture(sampling=True)
        w = 'networks' if len(l) > 1 else 'network '
        log.debug('|')
        log.debug(f'|_{len(l)} {w} of type {a}')
        sigmas, num = np.unique([n['sigma'] for n in l], return_counts=True)

        sigma_s = ' '.join([f'{sigma:.3e} ({n})'
                           for (sigma, n) in zip(sigmas, num)])
        log.debug(f'| |_ sigma={sigma_s}')

    log.info('Is trained and is tested (*) or will be (.)')
    log.info('|ood is tested (*) or will be (.)')
    log.info('|| # trained epochs')
    log.info('||     directory')
    # log.info('|||')
    enough_trained = []
    n_trained = 0
    n_tested = 0
    n_to_be_tested = 0
    n_ood_computed = 0
    n_ood_to_be_computed = 0
    testsets =  set()
    sigmas =  set()
    archs =  set()

    networks_to_be_studied = []
    for n in sum(l_o_l_o_d_o_n, []):
        to_be_studied = all([filters[k].filter(n[k]) for k in filters])
        if to_be_studied:
            networks_to_be_studied.append(n)

    for n in networks_to_be_studied:

        net = n['net']
        # print('*** ', *n)
        is_tested = test_accuracy_if(jvae=net,
                                     dry_run=True,
                                     min_test_sample_size=min_test_sample_size,
                                     batch_size=batch_size,
                                     unfinished=unfinished_training,
                                     min_epochs=epochs)
        
        is_enough_trained = is_tested is not None
        will_be_tested = is_enough_trained and not is_tested

        ood_are_tested = test_ood_if(jvae=net,
                                     dry_run=True,
                                     min_test_sample_size=min_test_sample_size,
                                     batch_size=batch_size,
                                     unfinished=unfinished_training,
                                     min_epochs=epochs)

        if is_enough_trained:
            ood_will_be_computed = sum([not v for v in ood_are_tested.values()])
        else:
            ood_will_be_computed = 0

        is_derailed = False
        
        if is_enough_trained:
            d = n['dir']
            derailed = os.path.join(d, 'derailed')
            if args.cautious:
                try:
                    log.debug('Evaluation of one sample...')
                    net.evaluate(torch.randn(1, *net.input_shape))
                    log.debug('...done')
                except ValueError:
                    open(derailed, 'a').close()
                    log.debug(f'Net in {d} has been marked as derailed')

            is_derailed = os.path.exists(derailed)
            if not is_derailed:
                enough_trained.append(n)
                sigmas.add(n['sigma'])
                testsets.add(n['set'])
                archs.add(n['arch'])
            else:
                is_enough_trained = False
                will_be_tested = False
                ood_will_be_computed = 0

        if is_derailed:
            train_mark = '+'
            ood_mark = '+'
            log.info('++ Derailed net in %s',
                     n['dir'])
        else:
            if not is_enough_trained:
                train_mark = '|'
                ood_mark = '|'
            else:
                train_mark = '*' if is_tested else '.'
                ood_mark = '*' if not ood_will_be_computed else ood_will_be_computed

            _dir = n['dir'][:130]
            _dir2 = n['dir'][130:]
            log.info('%s%s %3d %s', 
                     train_mark,
                     ood_mark,
                     net.trained,
                     _dir)
            if _dir2:
                log.info('||' +
                         '     ' +
                         '_' * (130 - len(_dir2)) +
                         _dir2)
        
        n_trained += is_enough_trained
        n_tested += (is_tested is True)
        n_to_be_tested += will_be_tested
        n_ood_computed += (ood_are_tested is True)
        n_ood_to_be_computed += ood_will_be_computed

    log.info('||')
    log.info('|%s ood to be computed', n_ood_to_be_computed)
    log.info('%s tested nets (%s tests to be done)',
             n_trained,
             n_to_be_tested)

    dict_of_sets = dict()
    testsets_ = testsets.copy()
    for s in testsets:
        log.debug('Get %s dataset', s)
        _, testset = torchdl.get_dataset(s)
        dict_of_sets[s] = testset
        for n in testset.same_size:
            testsets_.add(n)

    for s in testsets_.difference(testsets):
        log.debug('Get %s dataset', s)
        _, oodset = torchdl.get_dataset(s)
        dict_of_sets[s] = oodset
        
    if not dry_run:
        for n in enough_trained:

            trained_set = n['net'].training['set']
            n['net'].to(device)
            
            log.info('Test %s with %s', n['dir'], trained_set)

            testset=dict_of_sets[trained_set]
            test_accuracy_if(jvae=n['net'],
                             testset=testset,
                             unfinished=unfinished_training,
                             min_epochs=epochs,
                             min_test_sample_size=min_test_sample_size,
                             batch_size=batch_size,
                             method='all')

            if ood_sample_size:
                oodsets = [dict_of_sets[n] for n in testset.same_size]
                test_ood_if(jvae=n['net'],
                            testset=testset,
                            unfinished=unfinished_training,
                            min_epochs=epochs,
                            test_sample_size=ood_sample_size,
                            min_test_sample_size=min_test_sample_size,
                            batch_size=batch_size,
                            method='all')
            
            n['net'].save(n['dir'])

    show_best = False
    show_best = True
    
    df = data_frame_results(enough_trained, show_best=show_best)

    formats = []

    def finite(u, f):
        if np.isnan(u):
            return ''
        if np.isinf(u):
            return 'inf'
        return f.format(u)

    def f_pc(u):
        return finite(100 * u, '{:.1f}')
    
    def f_db(u):
        return finite(u, '{:.1f}')
    
    for _ in df.columns:
        formats.append(f_pc)
    
    log.info('')
    log.info('')
    log.info('')
    
    pd.set_option('max_colwidth', 15)
    print(df.to_string(na_rep='', decimal=',', formatters=formats))

    for a in archs:
        arch_code = hashlib.sha1(bytes(a, 'utf-8')).hexdigest()[:6]
        print(arch_code,':\n', a)
    #print(df.to_string())
