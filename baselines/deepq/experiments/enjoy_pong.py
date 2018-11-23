import gym
import sys
sys.path.append('..')
sys.path.append('../..')
sys.path.append('../../..')
try:
    sys.path.remove('/home/alberto/baselines')
except:
    print("")
from baselines import deepq


def main():
    env = gym.make("PongNoFrameskip-v4")
    env = deepq.wrap_atari_dqn(env)
    model = deepq.learn(
        env,
        network="conv_only",
        total_timesteps=0,
        convs=[(32, 8, 4), (64, 4, 2), (64, 3, 1)],
        hiddens=[256],
        dueling=True,
    )

    while True:
        obs, done = env.reset(), False
        episode_rew = 0
        while not done:
            env.render()
            obs, rew, done, _ = env.step(model(obs[None])[0])
            episode_rew += rew
        print("Episode reward", episode_rew)


if __name__ == '__main__':
    main()