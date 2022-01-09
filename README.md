This script provides an example of how the [DORA](https://www.devops-research.com/research.html) metrics deployment 
frequency, lead time for changes, time to restore service, and change failure rate can be calculated from Octopus 
releases, deployments, and build information.

The dependencies for the script are downloaded and the script run with the example command below:

```bash
python3 -m venv my_env
. my_env/bin/activate
pip --disable-pip-version-check install -r requirements.txt
python3 main.py \
    --octopusUrl https://tenpillars.octopus.app \
    --octopusApiKey "#{ApiKey}" \
    --githubUser mcasperson \
    --githubToken "#{GitHubToken}" \
    --octopusSpace "#{Octopus.Space.Name}" \
    --octopusEnvironment "#{Octopus.Environment.Name}" \
    --octopusProject "Products Service, Audits Service, Octopub Frontend"
```