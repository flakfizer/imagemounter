#!/usr/bin/env python
import subprocess
import tempfile
import pytsk3
import util
import glob
import pdb
import sys
import os


def main():
    if os.geteuid():  # Not run as root
        print u'[-] This script needs to be ran as root!'
        sys.exit(1)
    if not sys.argv[1:]:
        print u'Usage:\n{0} path_to_image..'.format(sys.argv[0])
        sys.exit(1)
    images = sys.argv[1:]
    for num, image in enumerate(images):
        if not os.path.exists(image):
            print "[-] Image {0} does not exist, aborting!".format(image)
            break
        try:
            p = ImageParser(image)
            # Mount the base image using ewfmount
            if not p.mount_base():
                continue

            print u'[+] Mounted raw image [{num}/{total}], now mounting partitions...'.format(num=num + 1, total=len(images))
            for mountpoint in p.mount_partitions():
                raw_input('>>> Press a key to unmount the image...')
                util.unmount([u'umount'], mountpoint)
                p.partition_mountpoints.remove(mountpoint)
                continue

            print u'[+] Parsed all partitions for this image!'
            # write results
        except KeyboardInterrupt:
            print u'[+] User pressed ^C, aborting...'
            return None
        finally:
            p.clean()
        # All done with this image, unmount it
        print u'[+] Image processed, proceding with next image.'


class ImageParser(object):
    def __init__(self, path):
        path = os.path.expandvars(os.path.expanduser(path))
        if util.is_encase(path):
            self.type = 'encase'
        else:
            self.type = 'dd'
        self.paths = sorted(util.expand_path(path))
        self.name = os.path.split(path)[1]
        self.basemountpoint = u''
        self.partition_mountpoints = []
        self.image = None
        self.volumes = None

    def mount_base(self):
        '''
        Mount the image at a remporary path for analysis
        '''
        self.basemountpoint = tempfile.mkdtemp(prefix=u'image_mounter_')

        def _mount_base(paths):
            try:
                print u'[+] Mounting image {0}'.format(paths[0])
                cmd = [u'xmount', '--in', 'ewf' if self.type == 'encase' else 'dd']
                cmd.extend(paths)
                cmd.append(self.basemountpoint)
                subprocess.check_call(cmd)
                return True
            except Exception:
                print (u'[-] Could not mount {0} (see below), will try '
                                  'multi-file method').format(paths[0])
                return False
        return _mount_base(self.paths) or _mount_base(self.paths[:1])

    def mount_partitions(self):
        '''
        Generator that mounts every partition of this image and yields the
        mountpoint
        '''
        # ewf raw image is now available on basemountpoint
        # either as ewf1 file or as .dd file
        raw_path = glob.glob(os.path.join(self.basemountpoint, u'ewf1'))
        raw_path.extend(glob.glob(os.path.join(self.basemountpoint, u'*.dd')))
        raw_path = raw_path[0]
        try:
            self.image = pytsk3.Img_Info(raw_path)
            self.volumes = pytsk3.Volume_Info(self.image)
        except:
            print u'[?] Could not determine volume information, possible empty image?'
            return

        for p in self.volumes:
            try:
                d = pytsk3.FS_Info(self.image, offset=p.start * 512)
                offset = p.start * 512
                mountpoint = tempfile.mkdtemp(prefix=u'image_mounter_' + str(offset)
                                              + u'_')

                #mount -t ext4 -o loop,ro,noexec,noload,offset=241790330880 \
                #/media/image/ewf1 /media/a
                cmd = None
                if u'0x83' in p.desc.lower():
                    # ext
                    cmd = [u'mount', raw_path,
                           mountpoint, u'-t', u'ext4', u'-o',
                           u'loop,ro,noexec,noload,offset=' + str(offset)]
                    print u'[+] Mounting ext volume on {0}.'.format(
                        mountpoint)
                elif u'bsd' in p.desc.lower():
                    # ufs
                    #mount -t ufs -o ufstype=ufs2,loop,ro,offset=4294967296 \
                    #/tmp/image/ewf1 /media/a
                    cmd = [u'mount', raw_path,
                           mountpoint, u'-t', u'ufs', u'-o',
                           u'ufstype=ufs2,loop,ro,offset=' + str(offset)]
                    print u'[+] Mounting UFS volume on {0}.'.format(
                        mountpoint)
                elif u'0xFD' in p.desc.lower():
                    # ext
                    cmd = [u'mount', raw_path,
                           mountpoint, u'-t', u'ext4', u'-o',
                           u'loop,ro,noexec,noload,offset=' + str(offset)]
                    print u'[+] Mounting ext volume on {0}.'.format(
                        mountpoint)
                elif u'0x07' in p.desc.lower():
                    # NTFS
                    cmd = [u'mount', raw_path,
                           mountpoint, u'-t', u'ntfs', u'-o',
                           u'loop,ro,noexec,noload,offset=' + str(offset)]
                    print u'[+] Mounting ntfs volume on {0}.'.format(
                        mountpoint)
                else:
                    print u'[-] Unknown filesystem encountered: ' + p.desc
                if not cmd:
                    os.rmdir(mountpoint)
                    continue

                subprocess.check_call(cmd, stdout=subprocess.PIPE)
                self.partition_mountpoints.append(mountpoint)
                yield mountpoint
                del d
            except:
                print u'[-] Could not load partition {0}:{1}'.format(p.addr, p.desc)

    def clean(self):
        '''
        Helper method that removes all ties to the filesystem, so the image can
        be unmounted successfully
        '''
        print u'[+] Analysis complete, unmounting...'

        if self.image:
            self.image.close()
        del self.image
        del self.volumes
        for m in self.partition_mountpoints:
            if not util.unmount([u'umount'], m):
                pdb.set_trace()

        if not util.unmount([u'fusermount', u'-u'], self.basemountpoint):
            pdb.set_trace()
        print u'[+] All cleaned up.'

if __name__ == '__main__':
    main()