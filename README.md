# Import or Update Users via udm Scripts
Python scripts for Univention Corporate Server import/update on UCS version 5.2.x
The original udm_import from Univention was very handy for batch creates that occur every year for a client, however, it is not updated/supported since UCS 4.9.x.

These two scripts were created from the code base for my use case. In particular, the update script that allows adding the **networkAccess** flag (true) and the **PasswordRecoveryEmailVerified** to (true).

Dropping these here for anyone wanting that functionality back. 

These are **UNMAINTAINED**. Use at your own risk.

Command line parameters passed remain as the orginal udm_import. Example:
    
      python3 /opt/udm_import.py users/user create input.csv


The use case for the update script was to batch enable RADIUS authorization (as noted above) and confirm the email address (which, if it's wrong in the CSV, will generate a support request as the end user affected will never receive the token.) These are typically done separately for the initial seed here as not all users have network access authorized.

    python3 /opt/udm_update.py users/user modify input.csv

