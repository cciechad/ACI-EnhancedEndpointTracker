#!/bin/bash

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )/../"
# change working directory to root of project
cd $BASE_DIR
source $BASE_DIR/build/build_common.sh
TMP_DIR="/tmp/appbuild/"

self=$0
intro_video=""
private_key=""
app_mini="0"
enable_proxy="1"
build_standalone="0"
run_dev_standalone="0"
standalone_http_port="5000"
standalone_https_port="5001"
docker_image_name=""            # set by build_standalone_container

# create version.txt with commit info
function add_version() {
    # example output:
    # 923797471c147b67b1e71004a8873d61db8d8f82      - commit
    # 2018-09-27T10:12:48-04:00                     - date (iso format)
    # 1538057568                                    - date (unix timestamp)
    # agccie@users.noreply.github.com               - commit author
    # master                                        - commit branch
    git log --pretty=format:%H%n%aI%n%at%n%ae%n -1 > ./version.txt
    git rev-parse --abbrev-ref HEAD >> ./version.txt
}

# build container image including subset of source code and UI dist built
function build_container_image(){
    # allow user to set APP_MODE by prov-
    # by default builds with APP_MODE=0 in container but can override with first arg
    local app_mode="0"
    if [ "$1" == "app_mode" ] ; then
        app_mode="1"
    fi

    log "building standalone container $APP_VENDOR_DOMAIN/$APP_ID:$APP_VERSION (app_mode=$app_mode)"
    set -e
    add_version

    # cp app.json to Service directory for consumption by config.py
    cp ./app.json ./Service/
    cp ./version.txt ./Service/

    # execute UI build outside of the container and copy dist to folder during image build
    local bf_tmp="$TMP_DIR/$APP_ID.build/UIAssets/"
    local bf_src="$BASE_DIR/UIAssets/"
    local bf_dst="$TMP_DIR/$APP_ID/UIAssets/"
    # need to make sure final build is available id UIAssets/dist folder
    mkdir -p ./UIAssets/dist
    if [ "$(ls -A ./UIAssets)" ] ; then
        mkdir -p $TMP_DIR/$APP_ID.build/UIAssets
        if [ "$SKIP_FRONTEND" == "1" ] ; then
            log "skipping frontend build, adding minimum files to support packaging"
            if [ ! -d "$bf_dst" ] ; then
                mkdir -p $bf_dst
            fi
            echo "hello" > $bf_dst/app.html
            echo "hello" > $bf_dst/app-start.html
            cp -p $BASE_DIR/UIAssets/logo.png $bf_dst
        else
            if [ "$build_standalone" == "1" ] || [ "$run_dev_standalone" == "1" ] ; then
                ./build/build_frontend.sh -s $bf_src -d $bf_dst -t $bf_tmp -m "standalone"
                cp -p $BASE_DIR/UIAssets/logo.png $bf_dst/logo.png
            elif [ "$app_mini" == "1" ] ; then
                ./build/build_frontend.sh -s $bf_src -d $bf_dst -t $bf_tmp -m "app-mini"
                if [ -f "$BASE_DIR/UIAssets/logo_mini.png" ] ; then
                    cp -p $BASE_DIR/UIAssets/logo_mini.png $bf_dst/logo.png
                else
                    cp -p $BASE_DIR/UIAssets/logo.png $bf_dst/logo.png
                fi
            else
                ./build/build_frontend.sh -s $bf_src -d $bf_dst -t $bf_tmp -m "app"
                cp -p $BASE_DIR/UIAssets/logo.png $bf_dst/logo.png
            fi
        fi
        cp -rf $bf_dst/* ./UIAssets/dist/
    fi

    # build tmp docker container directly from Dockerfile
    log "building base container"
    docker_image_name=`echo "$APP_CONTAINER_NAMESPACE/$APP_ID:$APP_VERSION" | tr '[:upper:]' '[:lower:]'`
    tmp_image="$docker_image_name-TMP"
    ba="--build-arg APP_MODE=$app_mode "
    if [ "$enable_proxy" == "1" ] ; then
        if [ "$https_proxy" ] ; then ba="$ba --build-arg https_proxy=$https_proxy" ; fi
        if [ "$http_proxy" ] ; then ba="$ba --build-arg http_proxy=$http_proxy" ; fi
        if [ "$no_proxy" ] ; then ba="$ba --build-arg no_proxy=$no_proxy" ; fi
    fi
    log "cmd: docker build -t $docker_image_name $ba ./build/"
    docker build -t $tmp_image $ba ./build/

    # create dynamic keys which will be added to container private config
    PRIVATE_CONFIG="/home/app/config.py"
    if [ `which md5sum` ] ; then
        EKEY=`dd if=/dev/urandom bs=1 count=32 2>/dev/null | md5sum | egrep -o "^[a-f0-9]+"`
        EIV=`dd if=/dev/urandom bs=1 count=32 2>/dev/null | md5sum | egrep -o "^[a-f0-9]+"`
    elif [ `which md5` ] ; then
        EKEY=`dd if=/dev/urandom bs=1 count=32 2>/dev/null | md5 | egrep -o "^[a-f0-9]+"`
        EIV=`dd if=/dev/urandom bs=1 count=32 2>/dev/null | md5 | egrep -o "^[a-f0-9]+"`
    else
        EKEY=`dd if=/dev/urandom bs=1 count=32 2>/dev/null | base64`
        EIV=`dd if=/dev/urandom bs=1 count=32 2>/dev/null | base64`
    fi

    # use base docker file and add addition commands to copy source code into it
    # (will remove WORKDIR and CMD since they are in the tmpDocker file below)
    dockerfile=".tmpDocker"
    cat >$dockerfile <<EOL
FROM $tmp_image
# copy src into container
COPY ./Service/version.txt \$SRC_DIR/Service/
COPY ./Service/start.sh \$SRC_DIR/Service/
COPY ./Service/*.py \$SRC_DIR/Service/
COPY ./Service/app.json \$SRC_DIR/Service/
COPY ./Service/app.wsgi \$SRC_DIR/Service/
COPY ./Service/app \$SRC_DIR/Service/app
COPY ./UIAssets/dist/ \$SRC_DIR/UIAssets/
# set random key and remove 
RUN echo "EKEY=\"$EKEY\"" > $PRIVATE_CONFIG ; \
    echo "EIV=\"$EIV\"" >> $PRIVATE_CONFIG ; 

WORKDIR \$SRC_DIR/Service
CMD \$SRC_DIR/Service/start.sh
EXPOSE 443/tcp
EOL

    log "building final container"
    log "cmd: docker build -t $docker_image_name -f $dockerfile ./"
    docker build -t $docker_image_name -f $dockerfile ./
}

# run container previously built by build_standalone_container
function run_standalone_container() {

    log "deploying standalone container $APP_VENDOR_DOMAIN/$APP_ID:$APP_VERSION"
    container_name=`echo "$APP_ID\_$APP_VERSION" | tr '[:upper:]' '[:lower:]'`
    # run the container with volume mount based on BASE_DIR and user provided http and https ports
    local cmd="docker run -dit --restart always --name $container_name "
    cmd="$cmd -v $BASE_DIR/Service:/home/app/src/Service:ro "
    cmd="$cmd -v $BASE_DIR/Service/instance:/home/app/src/Service/instance:rw "
    if [ "$standalone_http_port" -gt "0" ] ; then
        cmd="$cmd -p $standalone_http_port:80 "
    fi
    if [ "$standalone_https_port" -gt "0" ] ; then
        cmd="$cmd -p $standalone_https_port:443 "
    fi
    cmd="$cmd $docker_image_name "
    log "starting container: $cmd"
    eval $cmd
}

# build app.json mini config file and write to provided output directory
function build_app_mini_json() {
    outfile="$1/app.json"
    log "write mini app.json to $outfile"
    set +e
out=`BASE_DIR="$BASE_DIR" python - <<END
import os, sys, json, traceback
fname = "%s/app.json" % os.environ["BASE_DIR"].strip()
try:
    if os.path.exists(fname):
        with open(fname, "r") as f:
            js = json.load(f)
            # add "Mini" to appid and "-Mini" to name and (Mini) to shortdesc
            js["appid"] = "%sMini" % js["appid"]
            js["name"] = "%s-Mini" % js["name"]
            js["shortdescr"] = "(Mini) %s" % js["shortdescr"]
            # statically set apicversion to 2.2(1n)
            js["apicversion"] = "2.2(1n)"
            # remove clustermanager
            js.pop("clustermanager", None)
            # pretty print result to stdout
            print json.dumps(js, sort_keys=True, indent=4, separators=(',', ':'))
            sys.exit(0)
except Exception as e:
    print("\n%s" % traceback.format_exc())
    sys.exit(1)
END`
    if [ "$?" == "1" ] ; then
        log "failed to create app.json mini file: $out"
        exit 1
    fi   
    set -e
    log "$out"
    echo -e "$out" > $outfile
}

# used to prep container image with bundled src code - executed from within container after git pull
function build_app() {
    set -e
    log "building application $APP_VENDOR_DOMAIN/$APP_ID"
    add_version

    # create workspace directory, setup required app-mode directories, and copy over required files
    log "building workspace/copying files to $TMP_DIR/$APP_ID"
    rm -rf $TMP_DIR/$APP_ID
    rm -rf $TMP_DIR/$APP_ID.build
    mkdir -p $TMP_DIR/$APP_ID/UIAssets
    mkdir -p $TMP_DIR/$APP_ID/Service
    mkdir -p $TMP_DIR/$APP_ID/Image
    mkdir -p $TMP_DIR/$APP_ID/Legal
    mkdir -p $TMP_DIR/$APP_ID/Media/Snapshots
    mkdir -p $TMP_DIR/$APP_ID/Media/Readme
    mkdir -p $TMP_DIR/$APP_ID/Media/License
    mkdir -p $TMP_DIR/$APP_ID.build
    if [ "$app_mini" == "0" ] ; then
        mkdir -p $TMP_DIR/$APP_ID/ClusterMgrConfig
    fi

    # build docker container (this also builds frontend and already dropped into tmp_dir)
    build_container_image "app_mode"
    log "saving docker container image to application"
    docker save $docker_image_name | gzip -c > $TMP_DIR/$APP_ID/Image/aci_appcenter_docker_image.tgz

    # copy source code to service
    cp -rp ./Service/* $TMP_DIR/$APP_ID/Service/
    cp -p ./app.json $TMP_DIR/$APP_ID/
    cp -p ./app.json $TMP_DIR/$APP_ID/Service/
    cp -p ./version.txt $TMP_DIR/$APP_ID/Service/

    # remove instance config if present
    rm -rf $TMP_DIR/$APP_ID/Service/instance/config.py
    # remove tests folder from Service
    rm -rf $TMP_DIR/$APP_ID/Service/tests
    if [ "$app_mini" == "0" ] ; then
        # dynamically create clusterMgrConfig
        conf=$TMP_DIR/$APP_ID/ClusterMgrConfig/clusterMgrConfig.json
        python ./cluster/kron/create_config.py \
                --image $docker_image_name \
                --name $APP_ID \
                --short_name $APP_SHORT_NAME \
                > $conf
    else
        # override app.json with app_mini
        log "overriding app.json with app_mini.json"
        build_app_mini_json "$TMP_DIR/$APP_ID/"
        chmod 755 $TMP_DIR/$APP_ID/app.json
        cp -p $TMP_DIR/$APP_ID/app.json $TMP_DIR/$APP_ID/Service/app.json
    fi

    # create media and legal files
    # (note, snapshots are required in order for intro_video to be displayed on appcenter
    if [ "$(ls -A ./Legal)" ] ; then
        cp -p ./Legal/* $TMP_DIR/$APP_ID/Legal/
    fi
    if [ "$(ls -A ./Media/Snapshots)" ] ; then
        cp -p ./Media/Snapshots/* $TMP_DIR/$APP_ID/Media/Snapshots/
    fi
    if [ "$(ls -A ./Media/Readme)" ] ; then
        cp -p ./Media/Readme/* $TMP_DIR/$APP_ID/Media/Readme/
        # if this is app_mini, then we need to append those details to the readme.txt file
        if [ -f $TMP_DIR/$APP_ID/Media/Readme/readme.txt ] && [ "$app_mini" == "1" ] ; then
            local readme=$TMP_DIR/$APP_ID/Media/Readme/readme.txt
            local mtxt=""
            mtxt="$mtxt Mini mode is intended for backwards compatibility with APIC 2.x and 3.x.\n"
            mtxt="$mtxt See external documentation for scaling recommendations. Use the standard\n"
            mtxt="$mtxt app for APIC 4.0 and above or checkout the standalone verison.\n"
            (echo -e $mtxt ; cat $readme ) > $readme.tmp
            mv $readme.tmp $readme
        fi
    fi
    if [ "$(ls -A ./Media/License)" ] ; then
        cp -p ./Media/License/* $TMP_DIR/$APP_ID/Media/License/
    fi

    if [ "$intro_video" ] ; then
        log "adding intro video $intro_video"
        mkdir -p $TMP_DIR/$APP_ID/Media/IntroVideo
        cp $intro_video $TMP_DIR/$APP_ID/Media/IntroVideo/IntroVideo.mp4
        chmod 777 $TMP_DIR/$APP_ID/Media/IntroVideo/IntroVideo.mp4
    elif [ -f ./Media/IntroVideo/IntroVideo.mp4 ] ; then
        log "adding default intro video"
        mkdir -p $TMP_DIR/$APP_ID/Media/IntroVideo
        cp ./Media/IntroVideo/IntroVideo.mp4 $TMP_DIR/$APP_ID/Media/IntroVideo/IntroVideo.mp4
        chmod 777 $TMP_DIR/$APP_ID/Media/IntroVideo/IntroVideo.mp4
    fi

    # execute packager
    log "packaging application"
    tar -zxf ./build/app_package/cisco_aci_app_tools-$app_pack.tar.gz -C $TMP_DIR/$APP_ID.build/ 
    if [ "$private_key" ] ; then
        python $TMP_DIR/$APP_ID.build/cisco_aci_app_tools-$app_pack/tools/aci_app_packager.py -f $TMP_DIR/$APP_ID -p $private_key
    else
        python $TMP_DIR/$APP_ID.build/cisco_aci_app_tools-$app_pack/tools/aci_app_packager.py -f $TMP_DIR/$APP_ID
    fi

    # cleanup
    rm -rf $TMP_DIR/$APP_ID.build
    rm -rf $TMP_DIR/$APP_ID

    #log "build complete: `ls -a $TMP_DIR/*.aci`"
    set +e
}


# help options
function display_help() {
    echo ""
    echo "Help documentation for $self"
    echo "    -h display this help message"
    echo "    -k [file] private key uses for signing app"
    echo "    -P [https] https port when running in standalone mode (use 0 to disable)"
    echo "    -p [http] http port when running in standalone mode (use 0 to disable)"
    echo "    -s build standalone container"
    echo "    -r run dev standalone container (this will trigger a standalone container build as well)"
    echo "    -v [file] path to intro video (.mp4 format)"
    echo "    -m mini-app build (excludes clusterMgrConfig for support on APIC 2.2.1n and above)"
    echo ""
    exit 0
}


optspec=":v:k:p:P:hsrm"
while getopts "$optspec" optchar; do
  case $optchar in
    v)
        intro_video=$OPTARG
        if [ ! -f $intro_video ] ; then
            echo "" >&2
            echo "intro video '$intro_video' not found, aborting build" >&2
            echo "" >&2
            exit 1
        fi
        ;;
    k)
        private_key=$OPTARG
        if [ ! -f $private_key ] ; then
            echo "" >&2
            echo "private key '$private_key' not found, aborting build" >&2
            echo "" >&2
            exit 1
        fi
        ;;
    m)
        app_mini="1"
        ;;
    p)
        if [[ $OPTARG =~ ^-?[0-9]+$ ]] ; then
            standalone_http_port=$OPTARG
        else
            echo "" >&2
            echo "invalid http port $OPTARG, aborting build" >&2
            echo "" >&2
            exit 1
        fi
        ;;
    P)
        if [[ $OPTARG =~ ^-?[0-9]+$ ]] ; then
            standalone_https_port=$OPTARG
        else
            echo "" >&2
            echo "invalid http port $OPTARG, aborting build" >&2
            echo "" >&2
            exit 1
        fi
        ;;
    r)
        run_dev_standalone="1"
        ;;
    s)
        build_standalone="1"
        ;;
    h)
        display_help
        exit 0
        ;;
    :)
        echo "Option -$OPTARG requires an argument." >&2
        exit 1
        ;;
    \?)
        echo "Invalid option: \"-$OPTARG\"" >&2
        exit 1
        ;;
  esac
done

if [ "$APP_FULL_VERSION" == "" ] ; then
    APP_FULL_VERSION=$APP_VERSION
fi
app_original_filename=$APP_VENDOR_DOMAIN-$APP_ID-$APP_VERSION.aci
app_final_filename=$APP_VENDOR_DOMAIN-$APP_ID-$APP_FULL_VERSION.aci

# after app build, need to append Mini to app name if app_mini
if [ "$app_mini" == "1" ] ; then
    mini="Mini"
    app_original_filename=$APP_VENDOR_DOMAIN-$APP_ID$mini-$APP_VERSION.aci
    app_final_filename=$APP_VENDOR_DOMAIN-$APP_ID$mini-$APP_FULL_VERSION.aci
fi

# reset APP_VERSION to APP_FULL_VERSION for docker info to reflect patch
APP_VERSION=$APP_FULL_VERSION

# check depedencies first and then execute build
if [ "$build_standalone" == "1" ] || [ "$run_dev_standalone" == "1" ] ; then
    check_build_tools "backend"
    build_container_image
    if [ "$run_dev_standalone" == "1" ] ; then
        run_standalone_container
    fi
else
    check_build_tools
    build_app

    if [ -f $TMP_DIR/$app_original_filename ] ; then
        mv $TMP_DIR/$app_original_filename ./$app_final_filename
    elif [ -f $TMP_DIR/$app_final_filename ] ; then
        mv $TMP_DIR/$app_final_filename ./$app_final_filename
    else
        log "$TMP_DIR/$app_original_filename and $app_final_filename not found"
    fi
    log "build complete: $app_final_filename"

fi

