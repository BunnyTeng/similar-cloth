import os
import sys
import tensorflow as tf
import resnet_model
import resnet_run_loop
import preprocess_image as pi

_NUM_CLASSES = 463
_NUM_IMAGES = {
    'train': 0,
    'test': 0
}

def parse_record(raw_record, is_training):
    context_features = {
        'image': tf.FixedLenFeature([], dtype=tf.string),
        'xmin': tf.FixedLenFeature([], dtype=tf.int64),
        'ymin': tf.FixedLenFeature([], dtype=tf.int64),
        'xmax': tf.FixedLenFeature([], dtype=tf.int64),
        'ymax': tf.FixedLenFeature([], dtype=tf.int64)
    }
    sequence_features = {
        'label': tf.FixedLenSequenceFeature([], dtype=tf.int64)
    }
    context_parsed, sequence_parsed = tf.parse_single_sequence_example(
        serialized=raw_record,
        context_features=context_features,
        sequence_features=sequence_features
    )
    bbox = {
        'ymin': context_parsed['ymin'],
        'xmin': context_parsed['xmin'],
        'ymax': context_parsed['ymax'],
        'xmax': context_parsed['xmax']
    }
    image_buffer = context_parsed['image']
    label = sequence_parsed['label']
    label.set_shape((_NUM_CLASSES))

    image = pi.preprocess(image_buffer, is_training, bbox)

    return image, label


def input_fn(is_training, data_path, batch_size, num_epochs=1, num_parallel_calls=1, multi_gpu=False):
    dataset = tf.data.TFRecordDataset(
        [data_path], num_parallel_reads=num_parallel_calls)

    num_images = is_training and _NUM_IMAGES['train'] or _NUM_IMAGES['test']

    return resnet_run_loop.process_record_dataset(dataset, is_training, batch_size, num_images, parse_record, num_epochs, num_parallel_calls, examples_per_epoch=num_images, multi_gpu=multi_gpu)


class Model(resnet_model.Model):
    def __init__(self, resnet_size, data_format=None, num_classes=_NUM_CLASSES, version=resnet_model.DEFAULT_VERSION):
        if resnet_size < 50:
            bottleneck = False
            final_size = 512
        else:
            bottleneck = True
            final_size = 2048
        super(Model, self).__init__(
            resnet_size=resnet_size,
            bottleneck=bottleneck,
            num_classes=num_classes,
            num_filters=64,
            kernel_size=7,
            conv_stride=2,
            first_pool_size=3,
            first_pool_stride=2,
            second_pool_size=7,
            second_pool_stride=1,
            block_sizes=_get_block_sizes(resnet_size),
            block_strides=[1, 2, 2, 2],
            final_size=final_size,
            version=version,
            data_format=data_format)


def _get_block_sizes(resnet_size):
    choices = {
        18: [2, 2, 2, 2],
        34: [3, 4, 6, 3],
        50: [3, 4, 6, 3],
        101: [3, 4, 23, 3],
        152: [3, 8, 36, 3],
        200: [3, 24, 36, 3]
    }
    try:
        return choices[resnet_size]
    except KeyError:
        err = ('Could not find layers for selected Resnet size.\n'
            'Size received: {}; sizes allowed: {}.'.format(resnet_size, choices.keys()))
        raise ValueError(err)


def model_fn(features, labels, mode, params):
    learning_rate_fn = resnet_run_loop.learning_rate_with_decay(
        batch_size=params['batch_size'], batch_denom=256,
        num_images=_NUM_IMAGES['train'], boundary_epochs=[30, 60, 80, 90],
        decay_rates=[1, 0.1, 0.01, 0.001, 1e-4])
    return resnet_run_loop.resnet_model_fn(features, labels, mode, Model,
                                           resnet_size=params['resnet_size'],
                                           weight_decay=1e-4,
                                           learning_rate_fn=learning_rate_fn,
                                           momentum=0.9,
                                           data_format=params['data_format'],
                                           version=params['version'],
                                           loss_filter_fn=None,
                                           multi_gpu=params['multi_gpu'])


def main(argv):
    parser = resnet_run_loop.ResnetArgParser(
        resnet_size_choices=[18, 34, 50, 101, 152, 200])

    parser.set_defaults(
        train_epochs=100,
        data_dir='./data',
        model_dir='./model'
    )

    flags = parser.parse_args(args=argv[1:])

    train_path = os.path.join(flags.data_dir, 'train.tfrecord')
    test_path = os.path.join(flags.data_dir, 'test.tfrecord')
    _NUM_IMAGES['train'] = sum(1 for _ in tf.python_io.tf_record_iterator(train_path))
    _NUM_IMAGES['test'] = sum(1 for _ in tf.python_io.tf_record_iterator(test_path))

    # batch_size=32
    # data_dir = './data',
    # model_dir = './model'
    # resnet_size = 50
    # version = 2
    # train_epochs = 100
    # epochs_between_evals = 1
    # max_train_steps = None

    resnet_run_loop.resnet_main(flags, model_fn, input_fn)


if __name__ == '__main__':
    tf.logging.set_verbosity(tf.logging.INFO)
    main(argv=sys.argv)
