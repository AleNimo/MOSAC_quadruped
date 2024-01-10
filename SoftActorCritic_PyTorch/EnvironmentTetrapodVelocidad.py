import numpy as np
from CoppeliaSocket import CoppeliaSocket

class Environment:
    def __init__(self, obs_sp_shape, act_sp_shape, dest_pos):
        '''
        Creates a 3D environment using CoppeliaSim, where an agent capable of choosing its joints' angles tries to find
        the requested destination.
        :param obs_sp_shape: Numpy array's shape of the observed state
        :param act_sp_shape: Numpy array's shape of the action
        :param dest_pos: Destination position that the agent should search
        '''
        self.name = "ComplexAgentSAC"
        self.obs_sp_shape = obs_sp_shape                        # Observation space shape
        self.act_sp_shape = act_sp_shape                        # Action space shape
        self.dest_pos = np.array(dest_pos)                      # Agent's destination
        self.pos_idx = tuple(i for i in range(len(dest_pos)))   # Position's indexes in the observed state array
        self.__pos_size = len(dest_pos)                         # Position's size
        self.__end_cond = 2.5                                   # End condition
        self.__obs = np.zeros((1,)+self.obs_sp_shape)           # Observed state
        self.__coppelia = CoppeliaSocket(obs_sp_shape[0])     # Socket to the simulated environment

        #Parameters for forward velocity reward
        self.__target_velocity = 0.3 # m/s (In the future it could be a changing velocity)
        self.__vmax = 1
        self.__delta_vel = 0.3
        self.__vmin = -2

        self.__curvature_forward = -2*self.__vmax/(self.__delta_vel * self.__vmin)

        #Parameters for lateral velocity penalization
        self.__vmin_lat = -1
        self.__curvature_lateral = 3
        

        # #Parameters for orientation reward
        # self.__maxDecreaseOrientation = -0.5
        # self.__curvature = 1
        # self.__k = self.__maxDecreaseOrientation/(np.exp(-self.__curvature*np.pi)-1)#Auxiliary parameter to simplify equation
        
        #Parameters for flat back reward
        self.__vmin_back = -0.8
        self.__curvature_back = 2

        #Rewards at the end of the episode (either flipping or reaching the goal)
        self.__flipping_penalization = -2

    def reset(self):
        ''' Generates and returns a new observed state for the environment (outside of the termination condition) '''
        # Start position in (0,0) and random orientation (in z axis)
        pos = np.zeros(2)
        z_ang = 2*np.random.rand(1) - 1 #vector of 1 rand between -1 and 1, later multiplied by pi
        
        # Join position and angle in one vector
        pos_angle = np.concatenate((pos,z_ang))

        # Reset the simulation environment and obtain the new state
        self.__step = 0
        self.__obs = self.__coppelia.reset(pos_angle)
        return np.copy(self.__obs)

    def set_pos(self, pos):
        ''' Sets and returns a new observed state for the environment '''
        # Reset the simulation environment and obtain the new state
        self.__obs = self.__coppelia.reset(pos.reshape(-1))
        return np.copy(self.__obs)

    def get_pos(self):
        ''' Returns the current position of the agent in the environment '''
        # Return the position
        return self.__obs[0:self.__pos_size]

    def act(self, act):
        ''' Simulates the agent's action in the environment, computes and returns the environment's next state, the
        obtained reward and the termination condition status '''
        # Take the requested action in the simulation and obtain the new state
        next_obs = self.__coppelia.act(act.reshape(-1))
        # Compute the reward
        reward, end = self.__compute_reward_and_end(self.__obs.reshape(1,-1), next_obs.reshape(1,-1))
        # Update the observed state
        self.__obs[:] = next_obs
        # Return the environment's next state, the obtained reward and the termination condition status
        return next_obs, reward, end

    def compute_reward(self, obs):
        reward, _ = self.__compute_reward_and_end(obs[0:-1], obs[1:])
        return reward

    def __compute_reward_and_end(self, obs, next_obs):
        # Compute reward for every individual transition (state -> next_state)

            # Final distance to evaluate end condition
        dist_fin = np.sqrt(np.sum(np.square(next_obs[:,0:self.__pos_size]), axis=1, keepdims=True))

            # Velocity vector from every state observed
        forward_velocity = next_obs[:,7]
        lateral_velocity = next_obs[:,8]

            # Empty vectors to store reward and end flags for every transition
        reward, end = np.zeros((obs.shape[0], 1)), np.zeros((obs.shape[0], 1))

        for i in range(obs.shape[0]):

            '''Reward for forward velocity reaching target velocity'''

            forward_velocity_penalty = (self.__vmax - self.__vmin)/(self.__curvature_forward * np.abs(self.__target_velocity - forward_velocity[i]) + 1) + self.__vmin

            # print("forward_velocity = ", forward_velocity[i])
            # print("forward_velocity_penalty = ", forward_velocity_penalty)

            base_reward = forward_velocity_penalty

            '''Penalization for Lateral velocity'''
            lateral_velocity_penalty = -self.__vmin_lat/(self.__curvature_lateral * np.abs(lateral_velocity[i]) + 1) + self.__vmin_lat

            # print("lateral_velocity = ", lateral_velocity[i])
            # print("lateral_velocity_penalty = ", lateral_velocity_penalty)

            base_reward += lateral_velocity_penalty

            # '''Penalization for Orientation deviating from target direction'''
            # # Compute angle between agents orientation and target direction:
            # angle_agent2target = np.arctan2(next_obs[i,7], next_obs[i,8])

            # # Compute reward based on angle:
            # orientation_reward = self.__k*(np.exp(-self.__curvature * angle_agent2target) - 1)

            # if reward[i] < 0:
            #     reward[i] -= orientation_reward * reward[i]
            # else:
            #     reward[i] += orientation_reward * reward[i]

            '''Flat Back relative reward: pitch and roll close to 0°'''
            for j in range(5, 7):
                back_angle = np.abs(next_obs[i, j])*np.pi    #angle (in rad) of the back with respect to 0° (horizontal position)

                #if the angle is 0° the reward increases a __maxIncreaseBack of the base reward
                #if it is __neutralAngleBack or more, base reward is decreased (The mean of the X,Y angles is computed)

                flat_back_reward = -self.__vmin_back/(self.__curvature_back * back_angle + 1) + self.__vmin_back

                if base_reward < 0:
                    reward[i] -= flat_back_reward * base_reward * 0.5
                else:
                    reward[i] += flat_back_reward * base_reward * 0.5

                # print("back_angle ({0}) = {1:.2f}".format(j, back_angle))
                # print("Flat_back_reward ({0}) = {1:.2f}".format(j, flat_back_reward))

                reward[i] += flat_back_reward
            
            # print("Total_reward = ", reward[i])

            '''Penalization for flipping downwards'''
            #If the absolute value of X or Y angle is greater than 50° there is a penalization and the episode ends
            if abs(next_obs[i, 5]) >= 0.278 or abs(next_obs[i, 6]) >= 0.278:
                reward[i] += self.__flipping_penalization
                end[i] = True

            elif dist_fin[i] >= self.__end_cond:
                end[i] = True
                # print("finaliza")
            else:
                end[i] = False

            # print("reward = ", reward[i])
            # print("end = ", end[i])

        return reward, end

    def max_ret(self, obs):
        ''' Computes and returns the maximum return for the state '''
        return 100*np.sqrt(np.sum(np.square(obs.reshape(1,-1)[:,0:self.__pos_size]), axis=1, keepdims=True))