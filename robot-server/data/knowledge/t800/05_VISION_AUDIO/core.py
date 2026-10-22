"""Controle determinístico em graus; transporte ROS converte para radianos."""
import math
import time


class Refused(ValueError):
    pass


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise Refused('Informe números finitos, em graus.')
    return float(value)


class Controller:
    LIMITS = (20.0, 45.0)  # Envelope inicial menor que o URDF: pitch ±29.97°, yaw ±70.02°.
    SPEED = 8.0  # velocidade máxima da referência, graus/s
    LEASE = 0.7
    STATE_TIMEOUT = 0.5
    MOTION_TIMEOUT = 1.5

    def __init__(self, simulation=True, enabled=False, clock=time.monotonic):
        self.clock = clock
        self.simulation = simulation
        self.enabled = simulation or enabled
        self.actual = [0., 0.] if simulation else None
        self.command = [0., 0.]
        self.target = [0., 0.]
        self.start = [0., 0.]
        self.start_time = 0.
        self.duration = 1.
        self.state_at = self.motion_at = -math.inf
        self.motion = 'lower_body_balance' if simulation else ''
        self.count = 25 if simulation else 0
        self.conflicts = []
        self.subscribers = 1 if simulation else 0
        self.armed = False
        self.owner = None
        self.pulse_at = -math.inf
        self.release_frames = 0
        self.reason = 'Pronto para simular.' if simulation else 'Aguardando telemetria.'

    def feedback(self, positions):
        if len(positions) != 25:
            self.actual = None
            self.count = len(positions)
            return
        p = [math.degrees(number(positions[i])) for i in (23, 24)]
        self.actual, self.count, self.state_at = p, len(positions), self.clock()
        if self.reason == 'Aguardando telemetria.':
            self.reason = 'Telemetria conectada. Controle desarmado.'

    def motion_feedback(self, motion):
        self.motion, self.motion_at = motion, self.clock()

    def blockers(self):
        if self.simulation:
            return []
        reasons = []
        now = self.clock()
        if not self.enabled:
            reasons.append('Somente leitura: iniciar com --enable-motion para habilitar comandos.')
        if self.actual is None or now - self.state_at > self.STATE_TIMEOUT:
            reasons.append('Sem telemetria recente das 25 juntas do T800 básico.')
        if now - self.motion_at > self.MOTION_TIMEOUT or self.motion != 'lower_body_balance':
            reasons.append('O robô precisa confirmar lower_body_balance pela telemetria.')
        if self.conflicts:
            reasons.append('Outro publicador de controle presente: ' + ', '.join(self.conflicts))
        if self.subscribers == 0:
            reasons.append('Não há receptor do comando de pescoço.')
        if self.actual is not None and any(abs(v) > limit for v, limit in zip(self.actual, self.LIMITS)):
            reasons.append('Posição medida fora do envelope inicial (pitch ±20°, yaw ±45°).')
        return reasons

    def arm(self, owner):
        if self.armed:
            raise Refused('Já existe uma sessão de controle ativa.')
        reasons = self.blockers()
        if reasons:
            raise Refused(' '.join(reasons))
        self.command = self.target = self.start = list(self.actual)
        self.start_time = self.clock()
        self.armed, self.owner, self.pulse_at = True, owner, self.clock()
        self.release_frames = 0
        self.reason = 'Controle ativo enquanto o botão estiver pressionado.'

    def pulse(self, owner):
        if not self.armed or self.owner != owner:
            raise Refused('Sessão desarmada ou pertencente a outro navegador.')
        # Uma requisição atrasada nunca renova uma autorização vencida.
        if self.clock() - self.pulse_at > self.LEASE:
            self.disarm('Presença do operador expirou.')
            raise Refused(self.reason)
        self.pulse_at = self.clock()

    def move(self, owner, pitch, yaw):
        p = [number(pitch), number(yaw)]
        if any(abs(v) > limit for v, limit in zip(p, self.LIMITS)):
            raise Refused('Alvo fora do envelope: pitch ±20°, yaw ±45°.')
        self.pulse(owner)
        reasons = self.blockers()
        if reasons:
            self.disarm(' '.join(reasons))
            raise Refused(self.reason)
        now = self.clock()
        if now < self.start_time + self.duration and self.target != self.start:
            raise Refused('Aguarde terminar a trajetória antes de enviar outro alvo.')
        self.start = list(self.command)
        self.target = p
        # Máximo de ds/du da quíntica é 1.875: respeita SPEED em cada eixo.
        self.duration = max(1.0, 1.875 * max(abs(a-b) for a,b in zip(p,self.start)) / self.SPEED)
        self.start_time = now

    def disarm(self, reason='Controle liberado ao controlador principal.'):
        if self.armed:
            self.release_frames = 5
        self.armed, self.owner, self.reason = False, None, reason
        self.target = list(self.command)

    def tick(self):
        now = self.clock()
        if self.armed:
            reasons = self.blockers()
            if now - self.pulse_at > self.LEASE:
                reasons.append('Presença do operador expirou.')
            if self.actual is not None and max(abs(a-b) for a,b in zip(self.actual,self.command)) > 10:
                reasons.append('Erro entre posição medida e referência maior que 10°.')
            if reasons:
                self.disarm(' '.join(reasons))
        if self.armed:
            t = min(1., max(0., (now-self.start_time)/self.duration))
            s = 10*t**3 - 15*t**4 + 6*t**5
            self.command = [a+s*(b-a) for a,b in zip(self.start,self.target)]
            if self.simulation:
                self.actual = list(self.command)
            return self.packet(1.)
        if self.release_frames:
            self.release_frames -= 1
            return self.packet(0.)
        return None

    def packet(self, weight):
        return dict(weight=weight, joint_indices=[23,24],
                    position=[math.radians(p) for p in self.command],
                    velocity=[0.,0.], feed_forward_torque=[0.,0.], torque=[0.,0.],
                    stiffness=[100.,100.], damping=[3.,3.])

    def status(self):
        return dict(mode='simulação' if self.simulation else 'robô', enabled=self.enabled,
                    armed=self.armed, actual=self.actual, command=self.command, target=self.target,
                    moving=self.armed and self.clock() < self.start_time+self.duration and self.start != self.target,
                    motion=self.motion, blockers=self.blockers(), reason=self.reason,
                    feedback_age=None if self.state_at == -math.inf else round(self.clock()-self.state_at,3),
                    conflicts=self.conflicts, joint_count=self.count, limits=list(self.LIMITS))
