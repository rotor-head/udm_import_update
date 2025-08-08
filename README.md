# Import or Update Users via udm Scripts
Python scripts for Univention Corporate Server import/update on UCS version 5.2.x
The original udm_import from Univention was very handy for batch creates that occur every year for a client, however, it is not updated/supported since UCS 4.9.x.

These two scripts were created from the code base for my use case. In particular, the update script that allows adding the **networkAccess** flag (true) and the **PasswordRecoveryEmailVerified** to (true).

Dropping these here for anyone wanting that functionality back. 

These are **UNMAINTAINED**. Use at your own risk.
