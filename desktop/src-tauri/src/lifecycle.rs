use serde::Serialize;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum LifecycleState {
    Starting,
    Ready,
    Failed,
    Restarting,
    Stopping,
    Stopped,
}

#[derive(Debug)]
pub struct LifecycleMachine {
    state: LifecycleState,
    generation: u64,
}

impl Default for LifecycleMachine {
    fn default() -> Self {
        Self {
            state: LifecycleState::Stopped,
            generation: 0,
        }
    }
}

impl LifecycleMachine {
    pub fn state(&self) -> LifecycleState {
        self.state
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    pub fn start(&mut self) -> Result<u64, &'static str> {
        self.transition(LifecycleState::Starting)?;
        self.generation += 1;
        Ok(self.generation)
    }

    pub fn restart(&mut self) -> Result<u64, &'static str> {
        self.transition(LifecycleState::Restarting)?;
        self.generation += 1;
        Ok(self.generation)
    }

    pub fn ready(&mut self) -> Result<(), &'static str> {
        self.transition(LifecycleState::Ready)
    }

    pub fn fail(&mut self) -> Result<(), &'static str> {
        self.transition(LifecycleState::Failed)
    }

    pub fn begin_stop(&mut self) -> Result<(), &'static str> {
        self.transition(LifecycleState::Stopping)
    }

    pub fn stopped(&mut self) -> Result<(), &'static str> {
        self.transition(LifecycleState::Stopped)
    }

    fn transition(&mut self, next: LifecycleState) -> Result<(), &'static str> {
        use LifecycleState::{Failed, Ready, Restarting, Starting, Stopped, Stopping};
        let valid = matches!(
            (self.state, next),
            (Stopped, Starting)
                | (Starting, Ready | Failed | Stopping)
                | (Ready, Failed | Restarting | Stopping)
                | (Failed, Restarting | Stopping)
                | (Restarting, Ready | Failed | Stopping)
                | (Stopping, Stopped)
        );
        if !valid {
            return Err("invalid lifecycle transition");
        }
        self.state = next;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{LifecycleMachine, LifecycleState};

    #[test]
    fn startup_ready_failure_restart_and_stop_are_structural() {
        let mut machine = LifecycleMachine::default();
        assert_eq!(machine.start(), Ok(1));
        assert_eq!(machine.state(), LifecycleState::Starting);
        assert_eq!(machine.ready(), Ok(()));
        assert_eq!(machine.fail(), Ok(()));
        assert_eq!(machine.restart(), Ok(2));
        assert_eq!(machine.ready(), Ok(()));
        assert_eq!(machine.begin_stop(), Ok(()));
        assert_eq!(machine.stopped(), Ok(()));
    }

    #[test]
    fn failed_restart_can_be_retried_deliberately() {
        let mut machine = LifecycleMachine::default();
        machine.start().unwrap();
        machine.fail().unwrap();
        assert_eq!(machine.restart(), Ok(2));
        machine.fail().unwrap();
        assert_eq!(machine.restart(), Ok(3));
        machine.ready().unwrap();
    }

    #[test]
    fn invalid_and_overlapping_transitions_are_rejected() {
        let mut machine = LifecycleMachine::default();
        assert!(machine.restart().is_err());
        machine.start().unwrap();
        assert!(machine.start().is_err());
        machine.ready().unwrap();
        assert!(machine.ready().is_err());
        machine.begin_stop().unwrap();
        assert!(machine.fail().is_err());
    }

    #[test]
    fn quit_during_startup_and_restart_reaches_stopped() {
        for restart in [false, true] {
            let mut machine = LifecycleMachine::default();
            machine.start().unwrap();
            if restart {
                machine.fail().unwrap();
                machine.restart().unwrap();
            }
            machine.begin_stop().unwrap();
            machine.stopped().unwrap();
            assert_eq!(machine.state(), LifecycleState::Stopped);
        }
    }
}
