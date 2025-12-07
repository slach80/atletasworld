# Atletas World

Client-specific project for Atletas World.

## Project Structure

```
atletasworld/
├── src/                     # Client's specific source code
├── public/                  # Static content
├── resources/               # Shared resources (git submodule)
├── .gitignore               # Git ignore file
└── README.md                # This file
```

## Setup

1. Clone the repository with submodules:
   ```bash
   git clone --recurse-submodules https://github.com/slach80/atletasworld.git
   ```

2. If already cloned, initialize submodules:
   ```bash
   git submodule update --init --recursive
   ```

## Shared Resources

The `resources/` directory is a git submodule linking to [share-resources](https://github.com/slach80/share-resources). It contains reusable assets, scripts, and configurations shared across projects.

### Using Shared Scripts

Use the shared build and deploy scripts during development:

```bash
# Run the shared build script
./resources/scripts/build.sh

# Run the shared deploy script
./resources/scripts/deploy.sh
```

### Updating Shared Resources

When updates are pushed to shared-resources, update the submodule:

```bash
# Pull latest changes from shared-resources
git submodule update --remote resources

# Commit the submodule update
git add resources
git commit -m "Update shared-resources submodule"
git push
```
