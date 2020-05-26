from __future__ import print_function

import numpy as np
import torch
from cvae import ClassificationVariationalNetwork as CVNet
import data.torch_load as torchdl
import os
import sys
import argparse

from utils.parameters import alphanum, list_of_alphanums, get_args, set_log
from utils.save_load import collect_networks


if __name__ == '__main__':

    list_of_args = get_args('test')
    args = list_of_args[0]
    
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
    min_test_sample_size = args.min_test_sample_size

    for k in vars(args).items():
        log.debug('%s: %s', *k)
    
    search_dir = load_dir if load_dir else job_dir

    l_o_l_o_d_o_n = []
    collect_networks(search_dir, l_o_l_o_d_o_n) #, like=dummy_jvae)
    total = sum(map(len, l_o_l_o_d_o_n))
    log.debug(f'{total} networks in {len(l_o_l_o_d_o_n)} lists collected:')

    for (i, l) in enumerate(l_o_l_o_d_o_n):
        a = l[0]['net'].print_architecture(sampling=True)
        w = 'networks' if len(l) > 1 else 'network '
        log.debug(f'|_{len(l)} {w} of type {a}')
        betas, num = np.unique([n['beta'] for n in l], return_counts=True)
        beta_s = ' '.join([f'{beta:.3e} ({n})'
                           for (beta, n) in zip(betas, num)])
        log.debug(f'| |_ beta={beta_s}')

    log.info('Is trained')
    log.info('|Is tested')
    log.info('||')
    to_be_tested = []
    n_trained = 0
    n_tested = 0
    testsets = set()
    betas = set()

    for n in sum(l_o_l_o_d_o_n, []):

        # log.debug('Cuda me: %s', torch.cuda.memory_allocated())
        net = n['net']
        is_trained = net.trained >= net.training['epochs']
        is_tested = False
        if is_trained:
            to_be_tested.append(n)
            trained_set = net.training['set']
            betas.add(n['beta'])

            testsets.add(trained_set)
            testings_by_method = net.testing.get(trained_set,
                                        {None: {'epochs': 0, 'n':0}})
            enough_samples = True
            is_tested = True
            for m in testings_by_method:
                enough_samples = (enough_samples and
                                  testings_by_method[m]['n'] > min_test_sample_size)
                is_tested = is_tested and testings_by_method[m]['epochs'] == net.trained
                # log.debug('Tested at %s epochs (trained with %s) for %s',
                #           testings_by_method[m]['epochs'],
                #           net.trained,
                #           m)
        log.info('%s%s %s', 
                 '*' if is_trained else '|',
                 '*' if is_tested else '|',
                 n['dir'])
        
        n_tested = n_tested + is_tested
        n_trained = n_trained + is_trained

    log.info('||')
    log.info('|%s tested', n_tested)
    log.info('%s trained', n_trained)

    dict_of_sets = dict()
    for s in testsets:
        log.debug('Get %s dataset', s)
        _, testset = torchdl.get_dataset(s)
        dict_of_sets[s] = testset
        log.debug(testset)

    archs_by_set = {trained_set: dict() for s in testsets}
    
    for n in to_be_tested:
        
        trained_set = n['net'].training['set']
        log.info('Test %s with %s', n['dir'], trained_set)
        with torch.no_grad():
            n['net'].accuracy(dict_of_sets[trained_set],
                              print_result=True,
                              batch_size=batch_size, device=device,
                              method='all')
        n['net'].save(n['dir'])
        arch = n['net'].print_architecture()
        beta = n['beta']
        if arch not in archs_by_set[trained_set]:
            archs_by_set[trained_set][arch] = {b: [] for b in betas}

        archs_by_set[trained_set][arch][beta].append(n)

    method = 'loss'
        
    for s in archs_by_set:
        string = f'Networks trained for {s}'
        print(f'{string:_<{4 + 10 * len(betas)}}')
        print(' a\ß', end='')
        for beta in sorted(betas):
            print(f'{beta: ^10.2e}', end='')
        print()
        for i, arch in enumerate(archs_by_set[s]):
            print(f'{i:2}  ', end='')
            for beta in sorted(betas):
                max_acc = 0
                list_of_n = archs_by_set[s][arch][beta]
                for n in list_of_n:
                    acc = n['net'].testing[s][method]['accuracy']
                    if acc > max_acc: max_acc = acc
                
                print(f' {max_acc:7.2%}  ' if max_acc else ' ' * 10,
                      end='')
            print()
                    
