"""Searchable command guide transcribed from Paladin Scan manual rev. AA."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    template: str
    title: str
    description: str
    values: str = ""
    category: str = "Basic"
    risk: str = "query"  # query, operational, service


COMMANDS = (
    CommandSpec("BAUD=nnnnn", "Set baud rate", "Changes the controller baud rate; reconnect the app at the same rate. It resets to 9600 after power-off or RESET.", "9600, 14400, 19200, 28800, 38400", risk="service"),
    CommandSpec("?W", "Warm-up ready", "Reports whether warm-up is complete.", "0 = warming, 1 = ready"),
    CommandSpec("FP=n", "Front panel enable", "Enables or disables the controller front panel.", "0 = disabled, 1 = enabled", risk="operational"),
    CommandSpec("?FP", "Front panel status", "Reports whether the controller front panel is enabled.", "0 = disabled, 1 = enabled"),
    CommandSpec("L=n", "Laser diodes", "Starts the secured ramp-up or switches the laser diodes off. Start is allowed only from standby.", "0 = off, 1 = on", risk="operational"),
    CommandSpec("?L", "Laser-diode status", "Reports whether laser diodes are on.", "0 = off, 1 = on"),
    CommandSpec("P=n.m", "Set laser power", "Sets green output power in watts, only during warm-up or standby. Valid range is model-specific.", "Power in W", risk="operational"),
    CommandSpec("?P", "Actual laser power", "Returns actual green output power.", "W"),
    CommandSpec("?SP", "Power setpoint", "Returns the configured laser-power setpoint.", "W"),
    CommandSpec("S=n", "Beam shutter", "Closes or opens the beam shutter. Opening is available only in normal or alignment-ready operation.", "0 = closed, 1 = open", risk="operational"),
    CommandSpec("?S", "Shutter status", "Returns the actual beam-shutter status.", "0 = closed, 1 = open"),
    CommandSpec("D=n", "Display LEDs", "Turns display LEDs off or on.", "0 = off, 1 = on", risk="operational"),
    CommandSpec("?OPHn", "Operating hours", "Returns operating hours for a selected component.", "0 = head, 1 = oscillator diode, 3 = amplifier diode, 9 = supply"),
    CommandSpec("?SNn", "Serial number", "Returns the serial number for a selected component.", "0 = head, 1 = oscillator diode, 3 = amplifier diode, 9 = supply"),
    CommandSpec("?SPHSBR", "Current SBR spot hours", "Returns operating hours for the active SBR spot."),
    CommandSpec("?DTn", "Diode temperature", "Returns a laser-diode temperature.", "1 = oscillator, 3 = amplifier"),
    CommandSpec("?Tn", "Crystal temperature", "Returns an actual crystal temperature.", "0 = vanadate oscillator, 1 = resonator, 2 = vanadate amplifier, 5 = doubler, 7 = SBR"),
    CommandSpec("?STn", "Crystal set temperature", "Returns a crystal-temperature setpoint.", "0 = vanadate oscillator, 1 = resonator, 2 = vanadate amplifier, 5 = doubler, 7 = SBR"),
    CommandSpec("?HTn", "Heatsink temperature", "Returns a heatsink temperature.", "0 = laser head, 1 = power supply"),
    CommandSpec("?V", "Software version", "Returns controller software version."),
    CommandSpec("?LT", "Laser type", "Returns the configured laser type."),
    CommandSpec("?CIP", "Oscillator current", "Returns actual oscillator current in percent."),
    CommandSpec("?CIPA", "Amplifier current", "Returns actual amplifier current in percent."),
    CommandSpec("?SCIP", "Oscillator set current", "Returns oscillator current setpoint in percent."),
    CommandSpec("?SCIPA", "Amplifier set current", "Returns amplifier current setpoint in percent."),
    CommandSpec("?STA", "Operating status", "Returns the numeric laser operating state (decoded by the dashboard).", "0 ramp-up oscillator; 1 equilibration; 2 checking IR; 7 ramp-up light loop; 8 normal; 10 ramp-down; 11 standby; 12 warm-up; 13 alignment wait; 14 alignment ready"),
    CommandSpec("?LF", "Fault history", "Returns the last ten fault numbers and related head hours."),
    CommandSpec("CF", "Clear fault buffer", "Clears the stored fault buffer.", risk="operational"),
    CommandSpec("?PRO", "Rollover power", "Returns rollover power recorded during the last MAINT=1 start."),
    CommandSpec("?IRO", "Rollover current", "Returns rollover current percentage recorded during the last MAINT=1 start."),
    CommandSpec("SM=n", "Service mode", "Selects User or Service Mode; allowed only in standby or warm-up.", "0 = user, 1 = service", "Service", "service"),
    CommandSpec("?SM", "Service-mode status", "Reports User or Service Mode.", "0 = user, 1 = service", "Service"),
    CommandSpec("~", "Reset RS-232 communication", "Immediately resets the input and output buffers; this command has no terminator or response.", category="Service", risk="service"),
    CommandSpec("NP=n", "Communication protocol", "Selects Paladin-compatible replies or replies that also echo the command.", "0 = compatible, 1 = include command", "Service", "service"),
    CommandSpec("AM=n", "Alignment mode", "Switches between normal and alignment mode. Transition takes about 4-5 minutes.", "0 = normal, 1 = alignment", "Service", "service"),
    CommandSpec("?AM", "Alignment-mode status", "Returns alignment-mode status.", category="Service"),
    CommandSpec("AP+", "Increase green-detector adjustment", "Increases the internal green-detector adjustment.", category="Service", risk="service"),
    CommandSpec("AP-", "Decrease green-detector adjustment", "Decreases the internal green-detector adjustment.", category="Service", risk="service"),
    CommandSpec("AP0", "Reset green-detector adjustment", "Resets the internal green-detector adjustment to factory settings.", category="Service", risk="service"),
    CommandSpec("?AP", "Green-detector adjustment", "Queries internal green-detector adjustment.", category="Service"),
    CommandSpec("APIR+", "Increase IR-detector adjustment", "Increases the internal IR-detector adjustment.", category="Service", risk="service"),
    CommandSpec("APIR-", "Decrease IR-detector adjustment", "Decreases the internal IR-detector adjustment.", category="Service", risk="service"),
    CommandSpec("APIR0", "Reset IR-detector adjustment", "Resets the internal IR-detector adjustment to factory settings.", category="Service", risk="service"),
    CommandSpec("?APIR", "IR-detector adjustment", "Queries internal IR-detector adjustment.", category="Service"),
    CommandSpec("SWT=mnnnnn", "Set timer", "Sets the warm-up or ramp-up timer in seconds.", "m=1 warm-up, m=2 ramp-up", "Service", "service"),
    CommandSpec("?SWTm", "Timer remaining", "Returns seconds remaining for warm-up or ramp-up.", "m=1 warm-up, m=2 ramp-up", "Service"),
    CommandSpec("?SWTSETm", "Timer setpoint", "Returns the configured timer value.", "m=1 warm-up, m=2 ramp-up", "Service"),
    CommandSpec("MAINT=n", "Maintenance level", "Sets the EPROM-defined ramp-up procedure; normally 0.", "0 = standard, 1 = rollover determination", "Service", "service"),
    CommandSpec("?MAINT", "Maintenance level", "Returns the maintenance level.", category="Service"),
    CommandSpec("?EMBS", "EMBS loop status", "Returns the electromechanical beam-shutter loop status.", "0 = unknown/closed, 1 = closed/open, 2 = closed by loop", "Service"),
    CommandSpec("TF=n", "Transport flag", "Enables the slower post-transport temperature ramp.", "0 = reset, 1 = set", "Service", "service"),
    CommandSpec("?TF", "Transport flag", "Returns transport-flag status.", category="Service"),
    CommandSpec("SLL=value", "Green-power lower threshold", "Sets the lower green-power threshold.", category="Power control", risk="service"),
    CommandSpec("?LL", "Green-power lower threshold", "Returns the lower green-power threshold.", category="Power control"),
    CommandSpec("SHL=value", "Green-power upper threshold", "Sets the upper green-power threshold.", category="Power control", risk="service"),
    CommandSpec("?HL", "Green-power upper threshold", "Returns the upper green-power threshold.", category="Power control"),
    CommandSpec("?FL", "Green-power fault level", "Returns the green-power fault level.", category="Power control"),
    CommandSpec("?WR", "Power warning flag", "Returns whether green power left the selected range.", "0 = no warning, 1 = warning", "Power control"),
    CommandSpec("CWR", "Clear warning flags", "Clears green and IR warning flags.", category="Power control", risk="operational"),
    CommandSpec("CM=n", "Regulation mode", "Selects light-loop or current regulation; standby only.", "0 = light loop, 1 = current mode", "Current mode", "service"),
    CommandSpec("?CM", "Regulation mode", "Returns the regulation mode.", "0 = light loop, 1 = current mode", "Current mode"),
    CommandSpec("CIP=nnn.m", "Oscillator current", "Sets oscillator current percent in current mode.", category="Current mode", risk="service"),
    CommandSpec("CIPA=knnn.m", "Amplifier current", "Sets amplifier current percent in current mode (only k=0 is documented).", category="Current mode", risk="service"),
    CommandSpec("?SBRLIM", "SBR spot lifetime", "Returns the lifetime limit per SBR spot.", category="SBR"),
    CommandSpec("?SBRMAX", "SBR spot count", "Returns maximum SBR spot count.", category="SBR"),
    CommandSpec("?SBRHnn", "SBR spot hours", "Returns operating hours for SBR spot nn.", category="SBR"),
    CommandSpec("?SBRSTnn", "SBR spot status", "Returns status for SBR spot nn.", "0 = good, 1 = used, 2 = bad, 4 = in use", "SBR"),
    CommandSpec("?SPNSBR", "Current SBR spot", "Returns the active SBR spot number.", category="SBR"),
    CommandSpec("SHSBRm", "Shift SBR spot", "Shifts to a new SBR position and marks the old spot used or bad.", "0 = used, 1 = bad", "SBR", "service"),
    CommandSpec("SHSBRTO=mnn", "Shift to SBR spot", "Shifts to spot nn and marks the old spot used or bad.", "m=0 used, m=1 bad", "SBR", "service"),
    CommandSpec("?SBRALL", "All SBR data", "Returns SBR geometry plus status and hours for every spot.", category="SBR"),
    CommandSpec("?SBRTLIM", "SBR temperature limit", "Returns the SBR temperature warning limit.", category="SBR"),
    CommandSpec("SBRTLIM=value", "SBR temperature limit", "Sets the SBR temperature warning limit.", category="SBR", risk="service"),
    CommandSpec("?SBRWR", "SBR warning flag", "Returns SBR temperature warning status.", "0 = OK, 1 = warning", "SBR"),
    CommandSpec("SBRCWR", "Clear SBR warning", "Clears the SBR temperature warning flag.", category="SBR", risk="operational"),
    CommandSpec("SBRRSST=nn", "Reset SBR spot status", "Changes SBR spot nn status from BAD to USED.", category="SBR", risk="service"),
    CommandSpec("DBL=n", "Doubler optimization", "Enables or disables doubler optimization.", "0 = disabled, 1 = enabled", "SHG", "service"),
    CommandSpec("?DBL", "Doubler optimization", "Returns doubler-optimization status.", category="SHG"),
    CommandSpec("RESET", "Software reset", "Resets the power supply software.", category="SHG", risk="service"),
    CommandSpec("GOON", "Ignore warm-up", "Skips warm-up and proceeds to standby.", category="SHG", risk="service"),
    CommandSpec("SETVAN=nm.k", "Crystal set temperature", "Sets vanadate or resonator temperature (maximum six digits).", "n=0 oscillator, 1 resonator, 2 amplifier", "Temperature settings", "service"),
    CommandSpec("SETSHG=m.k", "SHG set temperature", "Sets SHG temperature (maximum six digits).", category="Temperature settings", risk="service"),
    CommandSpec("?KTALLS", "All monitoring data", "Returns the complete monitoring record in controller-defined field order.", category="Monitoring"),
    CommandSpec("?HWF", "Hardware fault", "Returns the hardware-fault field referenced by the monitoring record.", category="Monitoring"),
    CommandSpec("?SETTINGS", "All configured settings", "Returns all model-specific set values in controller-defined field order.", category="Settings"),
)


def search_commands(query: str) -> list[CommandSpec]:
    words = query.lower().split()
    if not words:
        return list(COMMANDS)
    return [
        spec
        for spec in COMMANDS
        if all(word in " ".join((spec.template, spec.title, spec.description, spec.values, spec.category)).lower() for word in words)
    ]


def command_risk(command: str) -> str:
    """Classify an entered command without pretending to validate service syntax."""
    upper = command.strip().upper().rstrip(";\r\n")
    if upper.startswith("?"):
        return "query"
    if upper in {"S=0", "L=0", "CF", "CWR", "SBRCWR"}:
        return "operational"
    if upper in {"S=1", "L=1"} or upper.startswith("P=") or upper.startswith("FP=") or upper.startswith("D="):
        return "operational"
    return "service"
