"""
File contains:

    - :class:`SOVNode`
    - :class:`SOVTree`

Author: W. Wybo
"""

import numpy as np

import itertools
import copy

import morphtree
from morphtree import MorphLoc
from phystree import PhysNode, PhysTree
from netree import NETNode, NET, Kernel

from neat.tools.fittools import zerofinding as zf
from neat.tools.fittools import histogramsegmentation as hs


def consecutive(data, stepsize=1):
    return np.split(data, np.where(np.diff(data) != stepsize)[0]+1)


class SOVNode(PhysNode):
    def __init__(self, index, p3d):
        super(SOVNode, self).__init__(index, p3d)

    def setSOV(self, tau_0=0.02):
        self.counter = 0
        # segment parameters
        self.g_m        = self.getGTot() # uS/cm^2
        # parameters for SOV approach
        self.R_sov      = self.R * 1e-4 # convert um to cm
        self.L_sov      = self.L * 1e-4 # convert um to cm
        self.tau_m      = self.c_m / self.g_m # s
        self.eps_m      = self.tau_m / tau_0
        self.lambda_m   = np.sqrt(self.R_sov / (2.*self.g_m*self.r_a)) # cm
        self.tau_0      = tau_0 # s
        self.z_a        = self.r_a / (np.pi * self.R_sov**2) # MOhm/cm
        self.g_inf_m    = 1. / (self.z_a * self.lambda_m) # uS
        # function for SOV approach
        self.q_m        = lambda x: np.sqrt(self.eps_m*x**2 - 1.)
        self.dq_dp_m    = lambda x: -self.tau_m / (2.*self.q_m(x))
        self.mu_m       = lambda x: 0. # has to be set recursively
        self.dmu_dp_m   = lambda x: 0. # has to be set recursively
        self.kappa_m    = lambda x: 0. # has to be set recursively
        # segment amplitude information
        self.kappa_m    = np.NaN
        self.mu_vals_m  = np.NaN
        self.q_vals_m   = np.NaN

    def setMuFunctions(self):
        if len(self.child_nodes) == 0:
            self.mu_m     = lambda x: self.z_a * self.lambda_m / self.q_m(x) * self.g_shunt
            self.dmu_dp_m = lambda x: -self.dq_dp_m(x) * self.mu_m(x) / self.q_m(x)
        else:
            cns = self.child_nodes
            def fun(x):
                x = zf._to_complex(x)
                mu_ds = [cn.mu_m(x) for cn in cns]
                q_ds  = [cn.q_m(x) for cn in cns]
                return ( self.g_shunt - np.sum([ \
                                cn.g_inf_m*q_ds[i] * \
                                ( 1.-mu_ds[i]/np.tan(q_ds[i]*cn.L_sov/cn.lambda_m) ) / ( 1./np.tan(q_ds[i]*cn.L_sov/cn.lambda_m)+mu_ds[i]) \
                                for i, cn in enumerate(cns)], 0) ) / (self.g_inf_m * self.q_m(x))
            self.mu_m = fun
            def dfun(x):
                x = zf._to_complex(x)
                mu_ds = [cn.mu_m(x) for cn in cns]
                dmu_dp_ds = [cn.dmu_dp_m(x) for cn in cns]
                q_ds  = [cn.q_m(x) for cn in cns]
                dq_dp_ds = [cn.dq_dp_m(x) for cn in cns]
                return (-self.dq_dp_m(x) * self.mu_m(x) - np.sum([ cn.g_inf_m * ( \
                                dq_dp_ds[i] * \
                                ( 1.-mu_ds[i]/np.tan(q_ds[i]*cn.L_sov/cn.lambda_m) ) / ( 1./np.tan(q_ds[i]*cn.L_sov/cn.lambda_m)+mu_ds[i]) + \
                                q_ds[i] * \
                                ( (1.+mu_ds[i]**2) * dq_dp_ds[i] * cn.L_sov/cn.lambda_m - dmu_dp_ds[i] ) / \
                                ( np.cos(q_ds[i]*cn.L_sov/cn.lambda_m) + mu_ds[i]*np.sin(q_ds[i]*cn.L_sov/cn.lambda_m) )**2 \
                                ) for i, cn in enumerate(cns)], 0) / self.g_inf_m ) / self.q_m(x)
            self.dmu_dp_m = dfun

    def setKappaFactors(self, xzeros):
        xzeros = zf._to_complex(xzeros)
        self.kappa_m = self.parent_node.kappa_m / \
                           (np.cos(self.q_m(xzeros)*self.L_sov/self.lambda_m) + \
                            self.mu_m(xzeros)*np.sin(self.q_m(xzeros)*self.L_sov/self.lambda_m))

    def setMuVals(self, xzeros):
        xzeros = zf._to_complex(xzeros)
        self.mu_vals_m = self.mu_m(xzeros)

    def setQVals(self, xzeros):
        xzeros = zf._to_complex(xzeros)
        self.q_vals_m = self.q_m(xzeros)

    def _findLocalPoles(self, maxspace_freq=500):
        poles = []
        pmultiplicities = []
        n = 0
        val = 0.
        while val < maxspace_freq:
            poles.append(np.sqrt((1.+val**2)/self.eps_m))
            if val == 0:
                pmultiplicities.append(.5)
            else:
                pmultiplicities.append(1.)
            n += 1
            val = n*np.pi * self.lambda_m / self.L_sov
        return poles, pmultiplicities

    def setZerosPoles(self, maxspace_freq=500, pprint=False):
        cns = self.child_nodes
        # find the poles of (1 + mu*cot(qL/l))/(cot(qL/l) + mu)
        lpoles, lpmultiplicities = self._findLocalPoles(maxspace_freq)
        for cn in cns:
            lpoles.extend(cn.poles)
            lpmultiplicities.extend(cn.pmultiplicities)
        inds = np.argsort(lpoles)
        lpoles = np.array(lpoles)[inds]; lpmultiplicities = np.array(lpmultiplicities)[inds]
        # construct the function cot(qL/l) + mu
        f = lambda x: 1./np.tan(self.q_m(x)*self.L_sov/self.lambda_m) + self.mu_m(x)
        dfdx = lambda x: -2.*x * ( -(self.L_sov/self.lambda_m)/np.sin(self.q_m(x)*self.L_sov/self.lambda_m)**2 * self.dq_dp_m(x) +\
                             self.dmu_dp_m(x) ) / self.tau_0
        # find its zeros, this are the poles of the next level
        xval = 1.5/np.sqrt(self.eps_m)
        for cn in cns:
            c_eps_m = cn.eps_m
            xval_ = 1.5/np.sqrt(c_eps_m)
            if  xval_ > xval:
                xval = xval_
        if np.abs(f(xval)) < 1e-20:
            xval = (xval+lpoles[1])/2.
        if pprint:
            print ''
            print 'xval: ', xval
        # find zeros larger than xval
        if pprint: print 'finding real poles'
        PF = zf.poleFinder(fun=f, dfun=dfdx, global_poles={'poles': lpoles, 'pmultiplicities': lpmultiplicities})
        poles, pmultiplicities = PF.find_real_zeros(vmin=xval)
        # find the first zero
        if pprint: print 'finding first pole'
        p1 = []; pm1 = []
        zf.find_zeros_on_segment(p1, pm1, 0., xval, f, dfdx, lpoles, lpmultiplicities, pprint=pprint)
        self.poles = np.concatenate((p1, poles)).real; self.pmultiplicities = np.concatenate((pm1, pmultiplicities)).real

class SomaSOVNode(SOVNode):
    '''
    Subclass of SOVNode to threat the special case of the soma

    The following member functions are not supposed to work properly,
    calling them may result in errors:
        :function:`setKappaFactors`
        :function:`setMuVals`
        :function:`setQVals`
        :function:`_findLocalPoles`
    '''
    def __init__(self, index, p3d):
        super(SOVNode, self).__init__(index, p3d)

    def setSOV(self, tau_0=0.02):
        self.counter = 0
        # convert to cm
        self.R_sov      = self.R * 1e-4 # convert um to cm
        self.L_sov      = self.L * 1e-4 # convert um to cm
        # surface
        self.A = 4.0*np.pi*self.R_sov**2 # cm^2
        # total conductance
        self.g_m        = self.getGTot() # uS/cm^2
        # parameters for the SOV approach
        self.tau_m      = self.c_m / self.g_m # s
        self.eps_m      = self.tau_m / tau_0 # ns
        self.g_s        = self.g_m*self.A + self.g_shunt # uS
        self.c_s        = self.c_m*self.A # uF
        self.tau_0      = tau_0  # s
        # functions for the SOV approach
        self.f_transc   = lambda x: 0.
        self.dN_dp      = lambda x: 0.
        # segment amplitude factors
        self.kappa_m = 1.

    def setMuFunctions(self):
        cns = self.child_nodes
        def fun(x):
            x = zf._to_complex(x)
            mu_ds = [cn.mu_m(x) for cn in cns]
            q_ds  = [cn.q_m(x) for cn in cns]
            return self.g_s * (1.-self.eps_m*x**2) - np.sum([ \
                         cn.g_inf_m*q_ds[i] * \
                        ( 1.-mu_ds[i]/np.tan(q_ds[i]*cn.L_sov/cn.lambda_m) ) / ( 1./np.tan(q_ds[i]*cn.L_sov/cn.lambda_m)+mu_ds[i]) \
                        for i, cn in enumerate(cns)], 0)
        self.f_transc = fun
        def dfun(x):
            x = zf._to_complex(x)
            mu_ds = [cn.mu_m(x) for cn in cns]
            dmu_dp_ds = [cn.dmu_dp_m(x) for cn in cns]
            q_ds  = [cn.q_m(x) for cn in cns]
            dq_dp_ds = [cn.dq_dp_m(x) for cn in cns]
            return self.c_s - np.sum([ cn.g_inf_m * ( \
                                dq_dp_ds[i] * \
                                ( 1.-mu_ds[i]/np.tan(q_ds[i]*cn.L_sov/cn.lambda_m) ) / ( 1./np.tan(q_ds[i]*cn.L_sov/cn.lambda_m)+mu_ds[i]) + \
                                q_ds[i] * \
                                ( (1.+mu_ds[i]**2) * dq_dp_ds[i] * cn.L_sov/cn.lambda_m - dmu_dp_ds[i] ) / \
                                ( np.cos(q_ds[i]*cn.L_sov/cn.lambda_m) + mu_ds[i]*np.sin(q_ds[i]*cn.L_sov/cn.lambda_m) )**2 \
                                ) for i, cn in enumerate(cns)], 0)
        self.dN_dp = dfun

    def setZerosPoles(self, maxspace_freq=500, pprint=False):
        # find the poles of cot(qL/l) + mu
        lpoles = []; lpmultiplicities = []
        for cn in self.child_nodes:
            lpoles.extend(cn.poles)
            lpmultiplicities.extend(cn.pmultiplicities)
        inds = np.argsort(lpoles)
        lpoles = np.array(lpoles)[inds]; lpmultiplicities = np.array(lpmultiplicities)[inds]
        # construct the function cot(qL/l) + mu
        f = lambda x: self.f_transc(x)
        dfdx = lambda x: -2.*x  * self.dN_dp(x) / self.tau_0
        # find its zeros, this are the inverse timescales of the model
        xval = 1.5/np.sqrt(self.eps_m)
        for cn in self.child_nodes:
            c_eps_m = cn.eps_m
            xval_ = 1.5/np.sqrt(c_eps_m)
            if  xval_ > xval:
                xval = xval_
        if np.abs(f(xval)) < 1e-20:
            xval = (xval+lpoles[1])/2.
        if pprint:
            print 'xval: ', xval
        # find zeros larger than xval
        PF = zf.poleFinder(fun=f, dfun=dfdx, global_poles={'poles': lpoles, 'pmultiplicities': lpmultiplicities})
        zeros, multiplicities = PF.find_real_zeros(vmin=xval)
        # find the first zero
        z1 = []; zm1 = []
        zf.find_zeros_on_segment(z1, zm1, 0., xval, f, dfdx, lpoles, lpmultiplicities, pprint=pprint)
        self.zeros = np.concatenate((z1, zeros)).real; self.zmultiplicities = np.concatenate((zm1, multiplicities)).real
        self.prefactors = self.dN_dp(self.zeros).real


class SOVTree(PhysTree):
    '''
    Class that computes the separation of variables time scales and spatial
    mode functions for a given morphology and electrical parameter set. Employs
    the algorithm by (Major, 1994). This three defines a special
    :class:`SomaSOVNode` on as a derived class from :class:`SOVNode` as some
    functions required for SOV calculation are different and thus overwritten.

    The SOV calculation proceeds on the computational tree (see docstring of
    :class:`MorphNode`). Thus it makes no sense to look for sov quantities in the
    original tree.
    '''
    def __init__(self, file_n=None, types=[1,3,4]):
        super(SOVTree, self).__init__(file_n=file_n, types=types)

    def createCorrespondingNode(self, node_index, p3d):
        '''
        Creates a node with the given index corresponding to the tree class.

        Parameters
        ----------
            node_index: int
                index of the new node
        '''
        if node_index == 1:
            return SomaSOVNode(node_index, p3d)
        else:
            return SOVNode(node_index, p3d)

    @morphtree.computationalTreetypeDecorator
    def getSOVMatrices(self, locs=None, name=None):
        '''
        returns the alphas, the reciprocals of the mode time scales [1/ms]
        as well as the spatial functions evaluated at ``locs``

        Parameters
        ----------
            locs: list of locations
            name: None or string
                One of the keyword arguments ``locs``, ``sov_data`` or ``name``
                must not be ``None``. If ``locs`` is not ``None``, the importance
                is evaluated at these locations.
                If ``name`` is not ``None``, it is the name of a previously
                stored set of locations

        Returns
        -------
            alphas: np.ndarray of complex (ndim = 1)
                the reciprocals of mode time-scales
            gammas: np.ndarray of complex (ndim = 2)
                the spatial function associated with each mode, evaluated at
                each locations. Dimension 0 is number of modes and dimension 1
                number of locations
        '''
        if locs is not None:
            pass
        elif name is not None:
            locs = self.getLocs(name)
        else:
            raise IOError('One of the kwargs `locs` or ' + \
                            '`name` must not be ``None``')
        # set up the matrices
        zeros      = self.root.zeros
        prefactors = self.root.prefactors
        alphas     = zeros**2 / (self.tau_0*1e3)
        gammas     = np.zeros((len(alphas), len(locs)), dtype=complex)
        # fill the matrix of prefactors
        for ii, loc in enumerate(locs):
            loc_ = MorphLoc(loc, self)
            if loc_['node'] == 1:
                x = 0.
                node = self.root.child_nodes[0]
            else:
                x = loc_['x']
                node = self[loc_['node']]
            # fill a column of the matrix, corresponding to current loc
            gammas[:, ii] = node.kappa_m * \
               (np.cos(node.q_vals_m*(1.-x)*node.L_sov/node.lambda_m) + \
               node.mu_vals_m * np.sin(node.q_vals_m*(1.-x)*node.L_sov/node.lambda_m)) / \
               np.sqrt(prefactors*1e3)
        # return the matrices
        return alphas, gammas

    @morphtree.computationalTreetypeDecorator
    def calcSOVEquations(self, maxspace_freq=500., pprint=False):
        '''
        Calculate the timescales and spatial functions of the separation of
        variables approach, using the algorithm by (Major, 1994).

        The (reciprocals) of the timescales (i.e. the roots of the transcendental
        equation) are stored in the somanode.
        The spatial factors are stored in each (computational) node.

        Parameters
        ----------
            maxspace_freq: float (default is 500)
                roughly corresponds to the maximal spatial frequency of the
                smallest time-scale mode
        '''
        self.tau_0 = np.pi#1.
        for node in self: node.setSOV(tau_0=self.tau_0)
        # start the recursion through the tree
        self._SOVFromLeaf(self.leafs[0], self.leafs[1:],
                            maxspace_freq=maxspace_freq, pprint=pprint)
        # zeros are now found, set the kappa factors
        zeros = self.root.zeros
        self._SOVFromRoot(self.root, zeros)
        # clean
        for node in self: node.counter = 0

    def _SOVFromLeaf(self, node, leafs, count=0,
                        maxspace_freq=500., pprint=False):
        if pprint:
            print 'Forward sweep: ' + str(node)
        pnode = node.parent_node
        # log how many times recursion has passed at node
        if not self.isLeaf(node):
            node.counter += 1
        # if the number of childnodes of node is equal to the amount of times
        # the recursion has passed node, the mu functions can be set. Otherwise
        # we start a new recursion at another leaf.
        if node.counter == len(node.child_nodes):
            node.setMuFunctions()
            node.setZerosPoles(maxspace_freq=maxspace_freq)
            if not self.isRoot(node):
                self._SOVFromLeaf(pnode, leafs, count=count+1,
                                maxspace_freq=maxspace_freq, pprint=pprint)
        elif len(leafs) > 0:
                self._SOVFromLeaf(leafs[0], leafs[1:], count=count+1,
                                maxspace_freq=maxspace_freq, pprint=pprint)

    def _SOVFromRoot(self, node, zeros):
        for cnode in node.child_nodes:
            cnode.setKappaFactors(zeros)
            cnode.setMuVals(zeros)
            cnode.setQVals(zeros)
            self._SOVFromRoot(cnode, zeros)

    def getModeImportance(self, locs=None, sov_data=None, name=None,
                                importance_type='relative'):
        '''
        Gives the overal importance of the SOV modes for a certain set of
        locations

        Parameters
        ----------
            locs: None or list of locations
            sov_data: None or tuple of mode matrices
            name: None or string
                One of the keyword arguments ``locs``, ``sov_data`` or ``name``
                must not be ``None``. If ``locs`` is not ``None``, the importance
                is evaluated at these locations. If ``sov_data`` is not ``None``,
                it is a tuple of a vector of the reciprocals of the mode time-
                scales and a matrix with the corresponding spatial mode functions.
                If ``name`` is not ``None``, it is the name of a previously
                stored set of locations
            importance_type: string ('relative' or 'absolute')
                when 'absolute', returns an absolute measure of the importance,
                when 'relative', normalizes so that maximum importance is one.
                Defaults to 'relative'.

        Returns
        -------
            np.ndarray (ndim = 1)
                the importances associated with each mode for the provided set
                of locations
        '''
        if name is not None:
            locs = self.getLocs(name)
            alphas, gammas = self.getSOVMatrices(locs)
        elif locs is not None:
            alphas, gammas = self.getSOVMatrices(locs)
        elif sov_data is not None:
            alphas = sov_data[0]
            gammas = sov_data[1]
        else:
            raise IOError('One of the kwargs `locs`, `sov_data` or \
                            `name` must not be ``None``')
        absolute_importance = np.sum(np.abs(gammas), 1) / np.abs(alphas)
        if importance_type == 'absolute':
            return absolute_importance
        elif importance_type =='relative':
            return absolute_importance / np.max(absolute_importance)
        else:
            raise ValueError('`importance_type` argument can be \'absolute\' or \
                              \'relative\'')

    def getImportantModes(self, locs=None, sov_data=None, name=None,
                                eps=1e-4, sort_type='timescale'):
        '''

        Parameters
        ----------
            locs: None or list of locations
            sov_data: None or tuple of mode matrices
            name: None or string
                One of the keyword arguments ``locs``, ``sov_data`` or ``name``
                must not be ``None``. If ``locs`` is not ``None``, the importance
                is evaluated at these locations. If ``sov_data`` is not ``None``,
                it is a tuple of a vector of the reciprocals of the mode time-
                scales and a matrix with the corresponding spatial mode functions.
                If ``name`` is not ``None``, it is the name of a previously
                stored set of locations
            eps: float
                the cutoff threshold in relative importance below which modes
                are truncated
            sort_type: string ('timescale' or 'importance')
                specifies in which order the modes are returned. If 'timescale',
                modes are sorted in order of decreasing time-scale, if
                'importance', modes are sorted in order of decreasing importance.

        Returns
        -------
            alphas: np.ndarray of complex (ndim = 1)
                the reciprocals of mode time-scales
            gammas: np.ndarray of complex (ndim = 2)
                the spatial function associated with each mode, evaluated at
                each locations. Dimension 0 is number of modes and dimension 1
                number of locations
        '''
        if name is not None:
            alphas, gammas = self.getSOVMatrices(self.getLocs(name))
            importance = self.getModeImportance(sov_data=(alphas, gammas))
        elif locs is not None:
            alphas, gammas = self.getSOVMatrices(locs)
            importance = self.getModeImportance(sov_data=(alphas, gammas))
        elif sov_data is not None:
            alphas = sov_data[0]
            gammas = sov_data[1]
            importance = self.getModeImportance(locs, sov_data=(alphas, gammas))
        else:
            raise IOError('At least one of the kwargs `locs`, `sov_data` or \
                            `name` must not be ``None``')
        inds = np.where(importance > eps)[0]
        if sort_type == 'timescale':
            inds_sort = np.argsort(np.abs(alphas[inds]))
        elif sort_type == 'importance':
            inds_sort = np.argsort(importance[inds])[::-1]
        else:
            raise ValueError('`sort_type` argument can be \'timescale\' or \
                              \'importance\'')
        return alphas[inds_sort], gammas[inds_sort,:]

    def calcImpedanceMatrix(self, locs=None, sov_data=None, name=None,
                                  eps=1e-4, mem_limit=500, freqs=None):
        '''
        Compute the impedance matrix for a set of locations

        Parameters
        ----------
            locs: None or list of locations
            sov_data: None or tuple of mode matrices
            name: None or string
                One of the keyword arguments ``locs``, ``sov_data`` or ``name``
                must not be ``None``. If ``locs`` is not ``None``, the importance
                is evaluated at these locations. If ``sov_data`` is not ``None``,
                it is a tuple of a vector of the reciprocals of the mode time-
                scales and a matrix with the corresponding spatial mode functions.
                If ``name`` is not ``None``, it is the name of a previously
                stored set of locations
            eps: float
                the cutoff threshold in relative importance below which modes
                are truncated
            mem_limit: int
                parameter governs whether the fast (but memory intense) method
                or the slow method is used
            freqs: np.ndarray of complex or None (default)
                if ``None``, returns the steady state impedance matrix, if
                a array of complex numbers, returns the impedance matrix for
                each Fourrier frequency in the array

        Returns
        -------
            np.ndarray of floats (ndim = 2)
                the impedance matrix
        '''
        if name is not None:
            alphas, gammas = self.getImportantModes(name=name, eps=eps)
        elif locs is not None:
            alphas, gammas = self.getImportantModes(locs=locs, eps=eps)
        elif sov_data is not None:
            alphas = sov_data[0]
            gammas = sov_data[1]
        else:
            raise IOError('At least one of the kwargs `locs`, `sov_data` or \
                            `name` must not be ``None``')
        n_loc = gammas.shape[1]
        if freqs is None:
            # construct the 2d steady state matrix
            y_activation = 1. / alphas
            # compute the matrix, methods depends on memory limit
            if gammas.shape[1] < mem_limit and gammas.shape[0] < int(mem_limit/2.):
                z_mat = np.sum(gammas[:,:,np.newaxis] * \
                               gammas[:,np.newaxis,:] * \
                               y_activation[:,np.newaxis,np.newaxis], 0).real
            else:
                z_mat = np.zeros((n_loc, n_loc))
                for ii, jj in itertools.product(xrange(n_loc), xrange(n_loc)):
                    z_mat[ii,jj] = np.sum(gammas[:,ii] * \
                                          gammas[:,jj] * \
                                          y_activation).real
        else:
            # construct the 3d fourrier matrix
            y_activation = 1e3 / (alphas[np.newaxis,:]*1e3 + freqs[:,np.newaxis])
            z_mat = np.zeros((len(freqs), n_loc, n_loc), dtype=complex)
            for ii, jj in itertools.product(xrange(n_loc), xrange(n_loc)):
                z_mat[:,ii,jj] = np.sum(gammas[np.newaxis,:,ii] * \
                                        gammas[np.newaxis,:,jj] * \
                                        y_activation, 1)
        return z_mat

    def constructNET(self, dz=50., dx=10., eps=1e-4,
                        use_hist=False, add_lin_terms=True,
                        pprint=False):
        '''
        Construct a Neural Evaluation Tree (NET) for this cell

        Parameters
        ----------
            dz: float
                the impedance step for the NET model derivation
            dx: float
                the distance step to evaluate the impedance matrix
            eps: float
                the cutoff threshold in relative importance below which modes
                are truncated
            use_hist: bool
                whether or not to use histogram segmentations to find well
                separated parts of the dendritic tree (such ass apical tree)
            add_lin_terms:
                take into account that the optained NET will be used in conjunction
                with linear terms

        Returns
            :class:`NETree`
        '''
        # create a set of location at which to evaluate the impedance matrix
        self.distributeLocsUniform(dx=dx, name='NET_eval')
        # compute the z_mat matrix
        alphas, gammas = self.getImportantModes(name='NET_eval', eps=eps)
        z_mat = self.calcImpedanceMatrix(sov_data=(alphas, gammas))
        # derive the NET
        net = NET()
        self._addLayerA(net, None,
                        z_mat, alphas, gammas,
                        0., 0, np.arange(len(self.getLocs('NET_eval'))),
                        dz=dz,
                        use_hist=use_hist, add_lin_terms=add_lin_terms,
                        pprint=pprint)
        if add_lin_terms:
            lin_terms = self.computeLinTerms(net, sov_data=(alphas, gammas))
            return net, lin_terms
        else:
            return net

    def _addLayerA(self, net, pnode,
                        z_mat, alphas, gammas,
                        z_max_prev, z_ind_0, true_loc_inds,
                        dz=100.,
                        use_hist=True, add_lin_terms=False,
                        pprint=False):
        # create a histogram
        n_bin = 15
        z_hist = np.histogram(z_mat[0,:], n_bin, density=False)
        # find the histogram partition
        h_ftc = hs.histogramSegmentator(z_hist)
        s_inds, p_inds = h_ftc.partition_fine_to_coarse(eps=1.4)

        # import matplotlib.pyplot as pl
        # xarr = (ghist[1][1:]+ghist[1][:-1])/2.
        # pl.plot(xarr, ghist[0], 'o--')
        # for si in sinds:
        #     pl.axvline(xarr[si], c='r')
        # for pi in pinds:
        #     pl.axvline(xarr[pi], c='g')
        # pl.show()
        #         # find the histogram partition
        # if np.max(z_mat[0,:]) - np.min(z_mat[0,:]) > 15.:
        #     h_ftc = funF.histogramSegmentator(ghist)
        #     sinds, pinds = h_ftc.partition_fine_to_coarse(eps=1.4)
        # else:
        #     h_ftc = funF.histogramSegmentator(ghist)
        #     sinds, pinds = h_ftc.partition_fine_to_coarse(eps=1.4)
        #     sinds = np.array([sinds[0], sinds[1]])

        # identify the necessary node indices and kernel computation indices
        node_inds  = []
        kernel_inds = []
        min_inds = []
        for ii, si in enumerate(s_inds[:-1]):
            if si > 0:
                n_inds = np.where(z_mat[0,:] > z_hist[1][si+1])[0]
                k_inds = np.where(np.logical_and(
                                    z_mat[0,:] > z_hist[1][si+1],
                                    z_mat[0,:] <= z_hist[1][s_inds[ii+1]+1]))[0]
                min_ind = np.argmin(z_mat[0,k_inds])
                min_inds.append(min_ind)
            else:
                n_inds = np.where(z_mat[0,:] >= z_hist[1][0])[0]
                k_inds = np.where(np.logical_and(
                                    z_mat[0,:] >= z_hist[1][0],
                                    z_mat[0,:] <= z_hist[1][s_inds[ii+1]+1]))[0]
                min_ind = np.argmin(z_mat[0,k_inds])
                min_inds.append(min_ind)
            node_inds.append(n_inds)
            kernel_inds.append(k_inds)

        # add NET nodes to the NET tree
        for ii, n_inds in enumerate(node_inds):
            k_inds = kernel_inds[ii]
            if len(k_inds) != 0:
                if add_lin_terms:
                    # get the minimal kernel
                    gammas_avg = gammas[:,0] * \
                                 gammas[:,k_inds[min_inds[ii]]]
                else:
                    # get the average kernel
                    if len(k_inds) < 100000:
                        gammas_avg = np.mean(gammas[:,0:1] * \
                                             gammas[:,kinds], 1)
                    else:
                        inds_ = np.random.choice(k_inds, size=100000)
                        gammas_avg = np.mean(gammas[:,0:1] * \
                                             gammas[:,inds_], 1)
                z_avg_approx = np.sum(gammas_avg / alphas).real
                self._subtractParentKernels(gammas_avg, pnode)
                # add a node to the tree
                node = NETNode(len(net), true_loc_inds,
                                z_kernel=(alphas, gammas_avg))
                if pnode != None:
                    net.addNodeWithParent(node, pnode)
                else:
                    net.root = node

                # print stuff
                if pprint:
                    print '>>> node index = ', node.index
                    if pnode != None:
                        print 'parent index = ', pnode.index
                    else:
                        print 'root node'
                    print '(locind0, size) = ', (k_inds[0], z_mat.shape[0])
                    print ''

                if k_inds[0] == 0:
                    # start new branches, split where they originate from soma by
                    # checking where input impedance is close to somatic transfer
                    # impedance
                    z_max = z_hist[1][s_inds[ii+1]]
                    # check where new dendritic branches start
                    z_diag = z_mat[k_inds, k_inds]
                    z_x0   = z_mat[k_inds, 0]
                    b_inds = np.where(np.abs(z_diag - z_x0) < dz / 2.)[0][1:].tolist()
                    if len(b_inds) > 0:
                        if b_inds[0] != 1:
                            b_inds = [1] + b_inds
                        kk = len(b_inds)-1
                        while kk > 0:
                            if b_inds[kk]-1 == b_inds[kk-1]:
                                del b_inds[kk]
                            kk -= 1
                    else:
                        b_inds = [1]
                    for jj, i0 in enumerate(b_inds):
                        # make new z_mat matrix
                        i1 = len(k_inds) if i0 == b_inds[-1] else b_inds[jj+1]
                        inds = np.meshgrid(k_inds[i0:i1], k_inds[i0:i1],
                                           indexing='ij')
                        z_mat_new = copy.deepcopy(z_mat[inds[0], inds[1]])
                        # move further in the tree
                        self._addLayerB(net, node,
                                    z_mat_new, alphas, gammas,
                                    z_max, k_inds[i0:i1], dz=dz,
                                    use_hist=use_hist, add_lin_terms=add_lin_terms)
                else:
                    # make new z_mat matrix
                    k_seqs = consecutive(k_inds)
                    if pprint:
                        print '\n>>> consecutive'
                        print 'nseq:', len(k_seqs)
                        for k_seq in k_seqs: print 'sequence:', k_seq
                    for k_seq in k_seqs:
                        inds = np.meshgrid(k_seq, k_seq, indexing='ij')
                        z_mat_new = copy.deepcopy(z_mat[inds[0], inds[1]])
                        z_max = z_mat[0,0]+1
                        # move further in the tree
                        self._addLayerB(net, node,
                                z_mat_new, alphas, gammas,
                                z_max, k_seq, dz=dz,
                                use_hist=use_hist, add_lin_terms=add_lin_terms)

    def _addLayerB(self, net, pnode,
                z_mat, alphas, gammas,
                z_max_prev, true_loc_inds, dz=100.,
                use_hist=True, pprint=False, add_lin_terms=False):
        # print stuff
        if pprint:
            print '>>> node index = ', node._index
            if pnode != None:
                print 'parent index = ', pnode._index
            else:
                print 'start'
        # get the diagonal
        z_diag = np.diag(z_mat)

        if true_loc_inds[0] == 0 and z_mat[0,0] > z_max_prev:
            n_bins = 'soma'
            z_max = z_mat[0,0] + 1.
            z_min = z_max_prev
        else:
            # histogram GF
            n_bins = max(int(z_mat.size/50.),
                         int((np.max(z_mat) - np.min(z_mat))/dz))
            if n_bins > 1:
                if np.all(np.diff(z_diag) > 0):
                    z_min = z_max_prev
                    z_max = z_min + dz
                    if pprint: print '--> +', dz
                elif use_hist:
                    z_hist = np.histogram(z_mat.flatten(), n_bins, density=False)
                    # find the histogram partition
                    h_ftc = funF.histogramSegmentator(z_hist)
                    s_ind, p_ind = h_ftc.partition_fine_to_coarse()

                    # get the new min max values
                    z_histx = z_hist[1]
                    z_min = z_max_prev
                    z_max = z_histx[s_ind[1]]
                    ii = 1
                    while np.min(z_diag) > z_histx[s_ind[i]]:
                        ii += 1
                        z_max = z_histx[s_ind[i]]
                    ii = np.argmax(z_hist[0][s_ind[0]:s_ind[i]])
                    z_avg = z_hist[0][ii]
                    if z_max - z_min > dz:
                        z_max = z_min + dz
                    if pprint: print '--> hist: +', str(z_max - z_min)
                else:
                    z_min = z_max_prev
                    z_max = z_min + dz
                    if pprint: print '--> +', dz
            else:
                z_min = z_max_prev
                z_max = np.max(z_mat)
                if pprint: print '--> all: +', str(z_max - z_min)
        d_inds = np.where(z_diag <= z_max+1e-15)[0]
        # make sure that there is at least one element in the layer
        while len(d_inds) == 0:
            z_max += dz
            d_inds = np.where(z_diag <= z_max+1e-15)[0]

        # identify different domains
        if add_lin_terms and true_loc_inds[0] == 0:
            t0 = np.array([1]); t1 = np.array([len(z_diag)])
        else:
            t0 = np.where(np.logical_and(z_diag[:-1] < z_max+1e-15,
                                         z_diag[1:] >= z_max+1e-15))[0]
            if len(t0) > 0: t0 += 1
            if z_diag[0] >= z_max+1e-15:
                t0 = np.concatenate(([0], t0))
            t1 = np.where(np.logical_and(z_diag[:-1] >= z_max+1e-15,
                                         z_diag[1:] < z_max+1e-15))[0]
            if len(t1) > 0: t1 += 1
            if z_diag[-1] >= z_max+1e-15:
                t1 = np.concatenate((t1, [len(z_diag)]))

        # identify where the kernels are within the interval
        l_inds = np.where(z_mat <= z_max+1e-15)

        # get the average kernel
        if l_inds[0].size < 100000:
            gammas_avg = np.mean(gammas[:,true_loc_inds[l_inds[0]]] * \
                                 gammas[:,true_loc_inds[l_inds[1]]], 1)
        else:
            inds_ = np.random.randint(l_inds[0].size, size=100000)
            gammas_avg = np.mean(gammas[:,true_loc_inds[l_inds[0]][inds_]] * \
                                 gammas[:,true_loc_inds[l_inds[1]][inds_]], 1)
        self._subtractParentKernels(gammas_avg, pnode)

        # add a node to the tree
        node = NETNode(len(net), true_loc_inds, z_kernel=(alphas, gammas_avg))
        if pnode != None:
            net.addNodeWithParent(node, pnode)
        else:
            net.root = node

        if pprint:
            print '(locind0, size) = ', (true_loc_inds[0], z_mat.shape[0])
            print '(zmin, zmax, n_bins) = ', (z_min, z_max, n_bins)
            print ''

        # move on to the next layers
        if len(d_inds) < len(z_diag):
            for jj, ind0 in enumerate(t0):
                ind1 = t1[jj]
                z_mat_new = copy.deepcopy(z_mat[ind0:ind1,ind0:ind1])
                true_loc_inds_new = true_loc_inds[ind0:ind1]
                self._addLayerB(net, node,
                            z_mat_new, alphas, gammas,
                            z_max, true_loc_inds_new, dz=dz,
                            use_hist=use_hist, pprint=pprint)

    def _subtractParentKernels(self, gammas, pnode):
        if pnode != None:
            gammas -= pnode.z_kernel['c']
            self._subtractParentKernels(gammas, pnode.parent_node)

    def computeLinTerms(self, net, sov_data=None, eps=1e-4):
        if sov_data != None:
            alphas = sov_data[0]
            gammas = sov_data[1]
        else:
            alphas, gammas = self.getImportantModes(name='NET_eval', eps=eps)
        lin_terms = []
        for ii, loc in enumerate(self.getLocs('NET_eval')):
            # create the true kernel
            z_k_true = Kernel((alphas, gammas[:,ii] * gammas[:,0]))
            # compute the NET approximation kernel
            z_k_net = net.getReducedTree([0, ii]).getRoot().z_kernel
            # compute the lin term
            lin_terms.append(z_k_true - z_k_net)
        return lin_terms
