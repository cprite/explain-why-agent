# Zetaris on AWS for free — simple setup

Based on Zetaris's own install guide (`docs/install/updated_zetaris_installation_guide.md`, section 4,
in github.com/zetaris/getting-started, 24 Sep 2026). Total time: about 1 hour, most of it waiting.

What you end up with: Zetaris running on a small Amazon server, opened in your browser at
`http://localhost:3000` through a secure SSH tunnel. Nothing is exposed to the internet.

## Part 1 — Download Zetaris (10 min, on your laptop)

1. Go to <https://www.zetaris.com/cloud> → **Start Free** → register (or sign in).
2. Open the **Run locally** page: <https://cloud.enterprise.zetaris.com/dashboard/download>.
3. Download **`zetaris-platform.zip`**.
4. On the same page, copy the **registry sign-in command** (it starts with
   `docker login zetarishackathon.azurecr.io`) and the sign-in details. Keep them in a note.
5. Move the zip out of Downloads, for example into a folder `~/zetaris`.

Licence: without a paid order the platform is for evaluation for up to 30 days. Signing up now
covers the build week and judging.

## Part 2 — Create the AWS account (15 min)

1. Create an account at <https://aws.amazon.com/resources/create-account/>. It asks for email,
   phone, a payment card and identity checks. Choose **Basic Support** (free).
2. Stay on the **Free plan**. New accounts get $100 of credits (up to $100 more through small
   "missions"). The Free plan lasts 6 months or until the credits run out.
3. In the console search bar open **Billing and Cost Management → Budgets** and create a **$10
   monthly cost budget** with an email alert at **$5**. This only warns you; it does not stop
   anything.

## Part 3 — Start the server (10 min, in the AWS console)

1. Top right, pick the region. The guide was tested in **Asia Pacific (Sydney)**; **Europe
   (London)** is closer to you and works the same way if `m7i-flex.large` shows as "Free tier
   eligible" there. If it doesn't, use Sydney.
2. Open **EC2 → Launch instance**.
   - **Name:** `zetaris-quickstart`
   - **Image:** Ubuntu Server **24.04 LTS**, **64-bit (x86)**
   - **Instance type:** `m7i-flex.large` (marked **Free tier eligible**)
   - **Key pair:** "Create new key pair" → name `zetaris` → type RSA → format `.pem` → it downloads
     `zetaris.pem`. Keep it safe.
   - **Network settings:** allow SSH traffic **from My IP** only. Leave HTTP and HTTPS unticked.
   - **Storage:** change to **40 GiB**, type **gp3**.
3. Click **Launch instance**. Wait until the state is **Running** and status checks pass.
4. Click the instance and copy its **Public IPv4 address**. Below it is written `YOUR_IP`.

## Part 4 — Install Zetaris on the server (30–45 min, in Terminal on your laptop)

Run these one block at a time. Replace `YOUR_IP` with the address from Part 3.

1. Send the zip to the server and log in:

   ```bash
   cd ~/zetaris
   chmod 600 ~/Downloads/zetaris.pem
   scp -i ~/Downloads/zetaris.pem zetaris-platform.zip ubuntu@YOUR_IP:~/
   ssh -i ~/Downloads/zetaris.pem ubuntu@YOUR_IP
   ```

   Answer `yes` the first time it asks about the fingerprint. You are now on the server.

2. Install Docker (Docker's official install script), then log out and back in so the change
   applies:

   ```bash
   sudo apt-get update && sudo apt-get install -y unzip
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker ubuntu
   exit
   ```

   ```bash
   ssh -i ~/Downloads/zetaris.pem ubuntu@YOUR_IP
   docker version && docker compose version
   ```

3. Unpack and sign in to Zetaris's image registry with the command from Part 1, step 4:

   ```bash
   unzip zetaris-platform.zip
   cd zetaris-platform
   docker login zetarishackathon.azurecr.io
   ./preflight.sh
   ```

   Warnings that memory is below 8 GB and there are fewer than 4 CPUs are expected on this size.

4. Edit the settings file:

   ```bash
   nano .env
   ```

   Set these lines (keep everything else as supplied):

   - `ZETARIS_ADMIN_EMAIL=` your email
   - `ZETARIS_ADMIN_PASSWORD=` a new password: at least 8 characters with lowercase, uppercase, a
     digit and one of `$ @ ! % * ? &` (no other punctuation)
   - `ZETARIS_ADMIN_ORG=` for example `MIRAZH`
   - `UI_PORT=127.0.0.1:3000`

   Save with `Ctrl+O`, `Enter`, then `Ctrl+X`.

5. Start it:

   ```bash
   chmod 600 .env
   docker compose config --quiet
   docker compose pull
   docker compose up -d
   ./verify.sh
   ```

   The first pull downloads several gigabytes. `verify.sh` should finish without errors.

## Part 5 — Open it (2 min)

1. Open a **second** Terminal window on your laptop and leave this running:

   ```bash
   ssh -i ~/Downloads/zetaris.pem -N -L 127.0.0.1:3000:127.0.0.1:3000 ubuntu@YOUR_IP
   ```

2. In your browser go to <http://localhost:3000> and sign in with the admin email and password
   from Part 4, step 4.
3. Open the **SQL Editor** and run `SELECT 1 AS one;`. One row with `1` means it works.

Tell Claude it is running. The next step is connecting it to the Raspberry Pi so the agents can use
it, which needs the server address and the `zetaris.pem` key file.

## Cost and switching off

| How you run it | Cost from credits |
| --- | --- |
| One 8-hour session | about $1 |
| Running day and night | about $3 a day; about $20 for the build week |
| Stopped (not terminated) | about $4 a month for the disk |

- **Pause:** EC2 → select the instance → **Instance state → Stop**. Start it again the same way.
  The public IP usually changes after a stop, so check it again before connecting.
- **Finish (after the hackathon):** **Instance state → Terminate**, then check **EC2 → Volumes**,
  **Elastic IPs** and **Billing** for anything left over.
- Stopping the containers does not stop AWS billing; only stopping or terminating the instance does.
