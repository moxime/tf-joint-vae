from __future__ import print_function

import numpy as np
import torch
from cvae import ClassificationVariationalNetwork as CVNet
import data.torch_load as torchdl
import os
import sys
import argparse

from utils.parameters import alphanum, list_of_alphanums, get_args, set_log, gethostname
from utils.save_load import collect_networks


if __name__ == '__main__':
    
    hostname = gethostname()

    args = get_args(what_for='train')
    
    debug = args.debug
    verbose = args.verbose

    job_dir = args.job_dir
    job_number = args.job_number
                
    log = set_log(verbose, debug, job_number=job_number)

    log.debug('$ ' + ' '.join(sys.argv))

    if not job_number:
        try:
            with open(os.path.join(job_dir, f'number-{hostname}')) as f:
                job_number = int(f.read())    
        except FileNotFoundError:
            log.warning(f'File number-{hostname} not found in {job_dir}')

    for k in args.__dict__.items():
        log.debug('%s: %s', *k)

    if job_number:
        log.info(f'Job number {job_number} started')
        
    if not args.force_cpu:
        device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        log.info(f'Used device: {device}')
    else:
        device = torch.device('cpu')
        log.info(f'Used device: {device}')
        log.debug(f'CPU asked by user')

    cuda_version = torch.version.cuda
    cudnn_version = torch.backends.cudnn.version()
    
    log.debug(f'Using cuda v. {cuda_version} and '
              f'cudnn v. {cudnn_version / 1000:.3f}')

    batch_size = args.batch_size
    test_sample_size = args.test_sample_size
    dry_run = args.dry_run    

    trainset, testset = torchdl.get_dataset(args.dataset, transformer=args.transformer)
    oodsets = [torchdl.get_dataset(n, transformer=args.transformer)[1]
               for n in testset.same_size]

    log.debug(f'{trainset.name} dataset loaded')

    input_shape, num_labels = torchdl.get_shape_by_name(args.dataset, args.transformer)

    rebuild = not args.resume

    args.optim_params = {
        'optim_type': args.optimizer,
        'lr': args.lr,
        'lr_decay':args.lr_decay,
        }

    if not rebuild:
        try:
            log.error('resume action not implemented')
            sys.exit(1)
            log.info('Loading network in %s', args.load_dir)
            jvae = CVNet.load(args.load_dir, load_state=True)
            log.debug(f'Network loaded')
            done_epochs = jvae.trained
            if done_epochs == 0:
                verb = 'will start from scratch.'
            elif done_epochs < args.epochs:
                verb = f'will resume from {done_epochs}.'
            else:
                verb = 'is already done.'
            log.info(f'Training {verb}')
        except(FileNotFoundError, NameError) as err:
            log.warning(f'Network not loaded -- rebuilding bc of {err}')
            rebuild = True

    if rebuild:
        input_shape, num_labels = torchdl.get_shape_by_name(args.dataset, args.transformer)
        _shape = '-'.join(map(str, input_shape + (num_labels,)))
        log.info('Building network for shape %s (%s with %s)',
                 _shape, args.dataset, args.transformer)

        jvae = CVNet(input_shape, num_labels,
                     type_of_net=args.type,
                     features=args.features,
                     features_channels=args.features_channels,
                     conv_padding=args.conv_padding,
                     pretrained_features=args.pretrained_features,
                     pretrained_upsampler=args.pretrained_upsampler,
                     batch_norm=args.batch_norm,
                     optimizer=args.optim_params,
                     encoder_layer_sizes=args.encoder,
                     latent_dim=args.latent_dim,
                     latent_sampling=args.latent_sampling,
                     decoder_layer_sizes=args.decoder,
                     upsampler_channels=args.upsampler,
                     classifier_layer_sizes=args.classifier,
                     learned_coder=args.learned_coder,
                     dictionary_min_dist=args.dict_min_distance,
                     coder_capacity_regularization=args.dict_distance_regularization,
                     sigma=args.sigma,
                     sigma_reach=args.sigma_reach,
                     output_activation=args.output_activation)

    _sigma_reach = f'--reach={args.sigma_reach:.1f}std' if args.sigma_reach else ''
    if not args.data_augmentation:
        _augment = ''
    else:
        _augment = '--augment='
        args.data_augmentation.sort()
        _augment += '-'.join(args.data_augmentation)

    save_dir_root = os.path.join(job_dir, args.dataset,
                                 jvae.print_architecture(sampling=False),
                                 f'sigma={args.sigma:1.2e}' +
                                 _sigma_reach +
                                 f'--optim={jvae.optimizer}' +
                                 f'--sampling={args.latent_sampling}'+
                                 _augment)

    save_dir = os.path.join(save_dir_root, f'{job_number:06d}')

    while os.path.exists(save_dir):
        log.debug(f'{save_dir} exists')
        job_number += 1
        save_dir = os.path.join(save_dir_root, f'{job_number:06d}')

    jvae.job_number = job_number

    with open(os.path.join(job_dir, f'number-{hostname}'), 'w') as f:
            f.write(str(job_number + 1) + '\n')

    log.info('Network built, will be saved in')
    log.info(save_dir)

    log.debug('%s: %s', 'Network architecture',
              jvae.print_architecture(True, True))

    jvae.to(device)

    x, y = torchdl.get_batch(trainset, device=device, batch_size=8)

    if debug:
        log.debug('Trying a first pass')
        log.debug('x in [%.2f, %.2f] with mean (std) %.2f (%.2f)',
                  x.min().item(),
                  x.max().item(),
                  x.mean().item(),
                  x.std().item())
        outs = jvae(x, y if jvae.y_is_coded else None)
        log.debug(' -- '.join(map(str,([tuple(u.shape) for u in outs]))))

    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    if not dry_run:
        if jvae.trained < args.epochs:
            log.info('Training of %s', jvae.print_architecture())

            #print('t.py l 302 testset:', testset.data[0].shape)
            jvae.train(trainset,
                       transformer=args.transformer,
                       epochs=args.epochs,
                       batch_size=batch_size,
                       device=device,
                       testset=testset,
                       oodsets=oodsets,
                       data_augmentation=args.data_augmentation,
                       fine_tuning=args.fine_tuning,
                       sample_size=test_sample_size,  # 10000,
                       save_dir=save_dir)
            log.info('Done training')
        else:
            log.info('No need to train %s', jvae.print_architecture())
    else:
        log.info('Dry-run %s', jvae.print_training(epochs=epochs, set=trainset.name))


    if save_dir is not None and not dry_run:
        jvae.save(save_dir)
