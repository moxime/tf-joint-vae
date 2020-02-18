import torch
from torch import nn, optim
import numpy as np
from torch.nn import functional as F

class Sampling(nn.Module):
    """Uses (z_mean, z_log_var) to sample z, the latent vector.
    - z_mean and a_log_var have the same dimensions NxK
    - the output z has dimensions LxNxK where L is the samoling size. 
    """

    def __init__(self, latent_dim, sampling_size=1, **kwargs):

        self.sampling_size = sampling_size
        super().__init__(**kwargs)

    def forward(self, z_mean, z_log_var):
        
        sampling_size = self.sampling_size
        size = (sampling_size,) + z_log_var.size()  
        epsilon = torch.randn(size)
        print((f'***** z_log_var: {z_log_var.size()} '+
               f'z_mean: {z_mean.size()} ' +
               f'epsilon: {epsilon.size()}'))
        return z_mean + torch.exp(0.5 * z_log_var) * epsilon

 
class Encoder(nn.Module):

    def __init__(self, input_shape, num_labels,
                 latent_dim=32,
                 intermediate_dims=[64],
                 name='encoder',
                 beta=0,
                 activation='relu',
                 sampling_size=10,
                 **kwargs):
        super(Encoder, self).__init__(**kwargs)
        self.name = name
        self.beta = beta
        self.kl_loss_weight = 2 * beta

        if activation == 'relu':
            self.activation = F.relu
        else raise ValueError(f'{activation} is not implemented in {self.__class__})')

        self.input_shape = input_shape
        self.num_labels = num_labels

        self.dense_projs = nn.ModuleList()
        input_dim = np.prod(input_shape) + num_labels
        for d in intermediate_dims:
            l_ = nn.Linear(input_dim, d)
            self.dense_projs.append(l_)
            input_dim = d

        self.dense_mean = nn.Linear(input_dim, latent_dim)
        self.dense_log_var = nn.Linear(input_dim, latent_dim)

        self.sampling = Sampling(latent_dim, sampling_size)
        
    def forward(self, x, y):
        """ 
        - x input of size NxD 
        - y of size Nx1
        - output of size (NxK, NxK, LxNxK)
        """
        # print('*****', 'x:', x.shape, 'y:', y.shape)
        u = torch.cat((x, y), dim=-1)
        for l in self.dense_projs:
            u = self.activation(l(u))
        z_mean = self.dense_mean(u)
        z_log_var = self.dense_log_var(u)
        z = self.sampling(z_mean, z_log_var)
        
        return z_mean, z_log_var, z

          
class Decoder(nn.Module):           # 
    """
    - input: N1 x N2 x ... Ng x K
    - output : N1 x... x Ng x D where D is product of dims of reconstructed dims)
    """
    def __init__(self, 
                 latent_dim, reconstructed_dim,
                 intermediate_dims=[64],
                 name='decoder',
                 activation='relu',
                 output_activation='sigmoid',
                 **kwargs):

        super(Decoder, self).__init__(**kwargs)
        self.name = name

        if activation == 'relu':
            self.activation = F.relu
        else raise ValueError(f'{activation} is not implemented in {self.__class__})')

        if output_activation == 'sigmoid':
            self.output_activation = F.sigmoid
        else raise ValueError(f'{output_activation} is not implemented in {self.__class__})')

        self.dense_layers = nn.ModuleList()
        input_dim = latent_dim
        for d in intermediate_dims:
            l_ = nn.Linear(input_dim, d)
            self.dense_layers.append(l_)
            input_dim = d

        self.output_layer = nn.Linear(input_dim, np.prod(reconstructed_dim))
      
    def forward(self, z):
        h = z
        # print('decoder inputs', inputs.shape)
        for l in self.dense_layers:
            # print('l:', l)
            h = self.activation(l(h))
        return self.output_activation(self.output_layer(h))
            

class Classifier(nn.Module):

    def __init__(self, latent_dim,
                 num_labels,
                 intermediate_dims=[],
                 name='classifier',
                 activation='relu',
                 **kwargs):

        super().__init__(**kwargs)
        self.name = name
        
        if activation == 'relu':
            self.activation = F.relu
        else raise ValueError(f'{output_activation} is not implemented in {self.__class__})')

        self.dense_layers = nn.ModuleList()
        input_dim = latent_dim
        for d in intermediate_dims:
            l_ = nn.Linear(input_dim, d)
            self.dense_layers.append(l_)
            input_dim = d

        self.output_layer = nn.Linear(input_dim, num_labels)
      
    def forward(self, z):
        u = z
        # print('decoder inputs', inputs.shape)
        for l in self.dense_layers:
            # print('l:', l)
            u = self(l(u))
        return self.output_layer(x).softmax(dim=-1)
