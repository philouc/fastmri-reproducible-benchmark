from keras.layers import Input, Lambda, Multiply, Conv2D, concatenate, Add
from keras.layers.advanced_activations import PReLU
from keras.models import Model
from keras.optimizers import Adam
import tensorflow as tf
from tensorflow.signal import fft2d, ifft2d

from utils import keras_psnr_complex, keras_ssim_complex


def to_complex(x):
    return tf.complex(x[0], x[1])

def conv2d_complex(x, n_filters, activation='relu'):
    x_real = Lambda(tf.math.real)(x)
    x_imag = Lambda(tf.math.imag)(x)
    if activation == 'prelu':
        act_real = PReLU()
        act_comp = PReLU()
    else:
        act_real = act_comp = activation
    conv_real = Conv2D(
        n_filters,
        3,
        activation=act_real,
        padding='same',
        kernel_initializer='he_normal',
    )(x_real)
    conv_imag = Conv2D(
        n_filters,
        3,
        activation=act_comp,
        padding='same',
        kernel_initializer='he_normal',
    )(x_imag)
    conv_res = Lambda(to_complex)([conv_real, conv_imag])
    return conv_res

def pdnet(input_size=(640, None, 1), n_filters=32, lr=1e-3, n_primal=5, n_dual=5, n_iter=10):
    kspace_input = Input(input_size, dtype='complex64')
    mask_shape = input_size[:-1]
    mask = Input(mask_shape, dtype='complex64')


    primal = Lambda(lambda x: tf.concat([tf.zeros_like(x)] * n_primal, axis=-1))(kspace_input)
    dual = Lambda(lambda x: tf.concat([tf.zeros_like(kspace_input)] * n_dual, axis=-1))(kspace_input)

    for i in range(n_iter):
        # first work in kspace (dual space)
        primal_sq = Lambda(tf.squeeze, output_shape=mask_shape, arguments={'axis': -1})(Lambda(lambda x: x[..., 1:2])(primal))
        dual_eval_fft = Lambda(fft2d, output_shape=mask_shape)(primal_sq)
        dual_eval_masked = Multiply()([dual_eval_fft, mask])
        dual_eval_exp = Lambda(tf.expand_dims, output_shape=input_size, arguments={'axis': -1})(dual_eval_masked)
        update = concatenate([dual, dual_eval_exp, kspace_input], axis=-1)

        update = conv2d_complex(update, n_filters, activation='relu')
        update = conv2d_complex(update, n_dual, activation='linear')
        dual = Add()([dual, update])


        # Then work in image space (primal space)
        dual_sq = Lambda(tf.squeeze, output_shape=mask_shape, arguments={'axis': -1})(Lambda(lambda x: x[..., 0:1])(dual))
        dual_masked = Multiply()([dual_sq, mask])
        primal_eval = Lambda(ifft2d, output_shape=mask_shape)(dual_masked)
        primal_exp = Lambda(tf.expand_dims, output_shape=input_size, arguments={'axis': -1})(primal_eval)
        update = concatenate([primal, primal_exp], axis=-1)

        update = conv2d_complex(update, n_filters, activation='relu')
        update = conv2d_complex(update, n_dual, activation='linear')
        primal = Add()([primal, update])

    image_res = Lambda(lambda x: x[..., 0:1])(primal)

    model = Model(inputs=[kspace_input, mask], outputs=image_res)
    model.compile(optimizer=Adam(lr=lr), loss='mean_absolute_error', metrics=['mean_squared_error', keras_psnr_complex, keras_ssim_complex])

    return model
