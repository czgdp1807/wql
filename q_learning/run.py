import sys
import os
import argparse
import numpy as np
import warnings
import time
from joblib import Parallel, delayed

from mushroom.core import Core
from mushroom.environments.generators.taxi import generate_taxi
from mushroom.utils.callbacks import CollectDataset, CollectQ
from mushroom.utils.dataset import parse_dataset
from mushroom.utils.parameters import ExponentialDecayParameter, Parameter
from mushroom.policy.td_policy import EpsGreedy, Boltzmann
from mushroom.algorithms.value.td import QLearning
from mushroom.utils.table import Table

from boot_q_learning import BootstrappedQLearning
from particle_q_learning import ParticleQLearning
sys.path.append('..')
from policy import BootPolicy, WeightedPolicy, VPIPolicy

from envs.chain import generate_chain
from envs.loop import generate_loop
from envs.river_swim import generate_river
from envs.six_arms import generate_arms

policy_dict = {'eps-greedy': EpsGreedy,
               'boltzmann': Boltzmann,
               'weighted': WeightedPolicy,
               'boot': BootPolicy,
               'vpi': VPIPolicy}

def compute_scores(dataset, gamma):
    scores = list()
    disc_scores = list()
    lens = list()

    score = 0.
    disc_score = 0.
    episode_steps = 0
    n_episodes = 0
    for i in range(len(dataset)):
        score += dataset[i][2]
        disc_score += dataset[i][2] * gamma ** episode_steps
        episode_steps += 1
        if dataset[i][-1]:
            scores.append(score)
            disc_scores.append(disc_score)
            lens.append(episode_steps)
            score = 0.
            episode_steps = 0
            n_episodes += 1

    if len(scores) > 0:
        return np.min(scores), np.max(scores), np.mean(scores), np.std(scores),  \
               np.min(disc_scores), np.max(disc_scores), np.mean(disc_scores), \
               np.std(disc_scores), np.mean(lens), n_episodes
    else:
        return 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0

def experiment(algorithm, name, update_mode, update_type, policy, n_approximators, q_max, q_min):
    np.random.seed()

    # MDP
    if name == 'Taxi':
        mdp = generate_taxi('grid.txt')
        max_steps = 1000000
        evaluation_frequency = 100000
        test_samples = 100000
    elif name == 'Chain':
        mdp = generate_chain(horizon=1000)
        max_steps = 100000
        evaluation_frequency = 10000
        test_samples = 10000
    elif name == 'Loop':
        mdp = generate_loop(horizon=1000)
        max_steps = 100000
        evaluation_frequency = 10000
        test_samples = 10000
    elif name == 'RiverSwim':
        mdp = generate_river(horizon=1000)
        max_steps = 100000
        evaluation_frequency = 10000
        test_samples = 10000
    elif name == 'SixArms':
        mdp = generate_arms(horizon=1000)
        max_steps = 100000
        evaluation_frequency = 10000
        test_samples = 10000
    else:
        raise NotImplementedError

    epsilon_test = Parameter(0)

    # Agent
    learning_rate = ExponentialDecayParameter(value=1., decay_exp=.3,
                                              size=mdp.info.size)
    algorithm_params = dict(learning_rate=learning_rate)

    if algorithm == 'ql':
        if policy not in ['boltzmann', 'eps-greedy']:
            warnings.warn('QL available with only boltzmann and eps-greedy policies!')
            policy = 'eps-greedy'
        epsilon_train = ExponentialDecayParameter(value=1., decay_exp=.5,
                                                  size=mdp.info.observation_space.size)
        if policy == 'eps-greedy':
            pi = policy_dict[policy](epsilon=epsilon_train)
        else:
            pi = policy_dict[policy](beta=epsilon_train)
        agent = QLearning(pi, mdp.info, **algorithm_params)
        agent.Q = Table(mdp.info.size, initial_value=q_max)

    elif algorithm == 'boot-ql':
        if policy not in ['boot', 'weighted']:
            warnings.warn('Bootstrapped QL available with only boot and weighted policies!')
            policy = 'boot'
        pi = policy_dict[policy](n_approximators=n_approximators)
        algorithm_params = dict(n_approximators=n_approximators,
                                mu=(q_max + q_min) / 2,
                                sigma=q_max - q_min,
                                **algorithm_params)
        agent = BootstrappedQLearning(pi, mdp.info, **algorithm_params)
        epsilon_train = Parameter(0)
    elif algorithm == 'particle-ql':
        if policy not in ['weighted', 'vpi']:
            warnings.warn('Particle QL available with only vpi and weighted policies!')
            policy = 'weighted'
        pi = policy_dict[policy](n_approximators=n_approximators)
        algorithm_params = dict(n_approximators=n_approximators,
                                update_mode=update_mode,
                                update_type=update_type,
                                q_max=q_max,
                                q_min=q_min,
                                **algorithm_params)
        agent = ParticleQLearning(pi, mdp.info, **algorithm_params)
        epsilon_train = Parameter(0)
    else:
        raise ValueError()

    # Algorithm
    collect_dataset = CollectDataset()
    collect_q = CollectQ(agent.approximator)
    callbacks = [collect_dataset, collect_q]
    core = Core(agent, mdp, callbacks)

    train_scores = []
    test_scores = []

    for n_epoch in range(1, max_steps // evaluation_frequency + 1):

        # Train
        if hasattr(pi, 'set_epsilon'):
            pi.set_epsilon(epsilon_train)
        if hasattr(pi, 'set_eval'):
            pi.set_eval(False)
        core.learn(n_steps=evaluation_frequency, n_steps_per_fit=1, quiet=True)
        dataset = collect_dataset.get()
        scores = compute_scores(dataset, mdp.info.gamma)
        print('Train: ', scores)
        train_scores.append(scores)


        collect_dataset.clean()
        mdp.reset()

        if hasattr(pi, 'set_epsilon'):
            pi.set_epsilon(epsilon_test)
        if hasattr(pi, 'set_eval'):
            pi.set_eval(True)
        dataset = core.evaluate(n_steps=test_samples, quiet=True)
        mdp.reset()
        scores = compute_scores(dataset, mdp.info.gamma)
        print('Evaluation: ', scores)
        test_scores.append(scores)

    return train_scores, test_scores

if __name__ == '__main__':

    parser = argparse.ArgumentParser()

    arg_game = parser.add_argument_group('Game')
    arg_game.add_argument("--name",
                          type=str,
                          default='RiverSwim',
                          help='Name of the environment to test.')

    arg_alg = parser.add_argument_group('Algorithm')
    arg_alg.add_argument("--algorithm",
                         choices=['ql', 'boot-ql', 'particle-ql'],
                         default='particle-ql',
                         help='The algorithm.')
    arg_alg.add_argument("--update-mode",
                          choices=['deterministic', 'randomized'],
                          default='deterministic',
                          help='Whether to perform randomized or deterministic target update (only ParticleQLearning).')
    arg_alg.add_argument("--update-type",
                          choices=['mean', 'distributional', 'weighted'],
                          default='weighted',
                          help='Kind of update to perform (only ParticleQLearning).')
    arg_alg.add_argument("--policy",
                          choices=['weighted', 'vpi', 'boot', 'boltzmann', 'eps-greedy'],
                          default='boot',
                          help='Kind of policy to use (not all available for all).')
    arg_alg.add_argument("--n-approximators", type=int, default=10,
                         help="Number of approximators used in the ensemble.")
    arg_alg.add_argument("--q-max", type=float, default=10000,
                         help='Upper bound for initializing the heads of the network (only ParticleQLearning).')
    arg_alg.add_argument("--q-min", type=float, default=0,
                         help='Lower bound for initializing the heads of the network (only ParticleQLearning).')

    arg_run = parser.add_argument_group('Run')
    arg_run.add_argument("--n-experiments", type=int, default=1,
                         help='Number of experiments to execute.')
    arg_run.add_argument("--dir", type=str, default='./data',
                         help='Directory where to save data.')

    args = parser.parse_args()

    fun_args = args.algorithm, args.name, args.update_mode, args.update_type, args.policy, args.n_approximators, args.q_max, args.q_min

    n_experiment = args.n_experiments

    affinity = len(os.sched_getaffinity(0))
    out = Parallel(n_jobs=affinity)(delayed(experiment)(*fun_args) for _ in range(n_experiment))

    out_dir = args.dir + '/' + args.name + '/' + args.algorithm
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    file_name = 'results_%s_%s_%s_%s' % (args.policy, '1' if args.algorithm == 'ql' else args.n_approximators,
                                         '' if args.algorithm != 'particle-ql' else args.update_type, time.time())
    np.save(out_dir + '/' + file_name, out)
