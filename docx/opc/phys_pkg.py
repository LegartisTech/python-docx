# encoding: utf-8

"""
Provides a general interface to a *physical* OPC package, such as a zip file or an xmlPackage stream.
"""

from __future__ import absolute_import

import os
from zipfile import ZipFile, is_zipfile, ZIP_DEFLATED

from docx.oxml import parse_xml
from lxml import etree

from .compat import is_string
from .exceptions import PackageNotFoundError
from .packuri import CONTENT_TYPES_URI

from base64 import b64decode

class PhysPkgReader(object):
    """
    Factory for physical package reader objects.
    """
    def __new__(cls, pkg_file):
        # if *pkg_file* is a string, treat it as a path
        if is_string(pkg_file):
            if os.path.isdir(pkg_file):
                reader_cls = _DirPkgReader
            elif is_zipfile(pkg_file):
                reader_cls = _ZipPkgReader
            else:
                raise PackageNotFoundError(
                    "Package not found at '%s'" % pkg_file
                )
        # if *pkg_file* is bytes, treat it as a package xml
        if isinstance(pkg_file, bytes):
            reader_cls = _XmlPkgReader
        else:  # assume it's a stream and pass it to Zip reader to sort out
            reader_cls = _ZipPkgReader

        return super(PhysPkgReader, cls).__new__(reader_cls)


class PhysPkgWriter(object):
    """
    Factory for physical package writer objects.
    """
    def __new__(cls, pkg_file):
        return super(PhysPkgWriter, cls).__new__(_ZipPkgWriter)


class _DirPkgReader(PhysPkgReader):
    """
    Implements |PhysPkgReader| interface for an OPC package extracted into a
    directory.
    """
    def __init__(self, path):
        """
        *path* is the path to a directory containing an expanded package.
        """
        super(_DirPkgReader, self).__init__()
        self._path = os.path.abspath(path)

    def blob_for(self, pack_uri):
        """
        Return contents of file corresponding to *pack_uri* in package
        directory.
        """
        path = os.path.join(self._path, pack_uri.membername)
        with open(path, 'rb') as f:
            blob = f.read()
        return blob

    def close(self):
        """
        Provides interface consistency with |ZipFileSystem|, but does
        nothing, a directory file system doesn't need closing.
        """
        pass

    @property
    def content_types_xml(self):
        """
        Return the `[Content_Types].xml` blob from the package.
        """
        return self.blob_for(CONTENT_TYPES_URI)

    def rels_xml_for(self, source_uri):
        """
        Return rels item XML for source with *source_uri*, or None if the
        item has no rels item.
        """
        try:
            rels_xml = self.blob_for(source_uri.rels_uri)
        except IOError:
            rels_xml = None
        return rels_xml


class _ZipPkgReader(PhysPkgReader):
    """
    Implements |PhysPkgReader| interface for a zip file OPC package.
    """
    def __init__(self, pkg_file):
        super(_ZipPkgReader, self).__init__()
        self._zipf = ZipFile(pkg_file, 'r')

    def blob_for(self, pack_uri):
        """
        Return blob corresponding to *pack_uri*. Raises |ValueError| if no
        matching member is present in zip archive.
        """
        return self._zipf.read(pack_uri.membername)

    def close(self):
        """
        Close the zip archive, releasing any resources it is using.
        """
        self._zipf.close()

    @property
    def content_types_xml(self):
        """
        Return the `[Content_Types].xml` blob from the zip package.
        """
        return self.blob_for(CONTENT_TYPES_URI)

    def rels_xml_for(self, source_uri):
        """
        Return rels item XML for source with *source_uri* or None if no rels
        item is present.
        """
        try:
            rels_xml = self.blob_for(source_uri.rels_uri)
        except KeyError:
            rels_xml = None
        return rels_xml


class _XmlPkgReader(PhysPkgReader):
    """
    Implements |PhysPkgReader| interface for a XML OPC package.
    """
    def __init__(self, pkg_file):
        super(_XmlPkgReader, self).__init__()
        self._root_element = parse_xml(pkg_file)
        pkg_name_attr_key = f'{{{self._root_element.nsmap["pkg"]}}}name'
        pkg_ct_attr_key = f'{{{self._root_element.nsmap["pkg"]}}}contentType'
        xml_data_elm = f'{{{self._root_element.nsmap["pkg"]}}}xmlData'
        xml_binary_data_elm = f'{{{self._root_element.nsmap["pkg"]}}}binaryData'
        parts = {}
        content_type_xml = etree.Element('Types', xmlns='http://schemas.openxmlformats.org/package/2006/content-types')
        etree.SubElement(content_type_xml, 'Default', Extension='xml', ContentType='application/xml')
        etree.SubElement(content_type_xml, 'Default', Extension='rels', ContentType='application/vnd.openxmlformats-package.relationships+xml')
        etree.SubElement(content_type_xml, 'Default', Extension='jpeg', ContentType='image/jpeg')
        for e in self._root_element:
            pkg_name_attr_value = e.get(pkg_name_attr_key)
            etree.SubElement(content_type_xml, 'Override', PartName=pkg_name_attr_value, ContentType=e.get(pkg_ct_attr_key))
            xmlDatas = e.findall(xml_data_elm)

            if len(xmlDatas) == 1 and len(xmlDatas[0]) == 1:
                parts.setdefault(pkg_name_attr_value, etree.tostring(xmlDatas[0][0]))
            elif len(xmlDatas) == 0:
                binaryDatas = e.findall(xml_binary_data_elm)
                if len(binaryDatas) == 1:
                    parts.setdefault(pkg_name_attr_value, b64decode(binaryDatas[0].text))
                else:
                    raise ValueError(f'Found {len(binaryDatas)} "binaryData" children or {len(binaryDatas[0])} grand children, only one each is expected!')
            else:
                raise ValueError(f'Found {len(xmlDatas)} "xmlData" children or {len(xmlDatas[0])} grand children, only one each is expected!')

        self._parts = parts
        self._content_type_xml = etree.tostring(content_type_xml)

    def blob_for(self, pack_uri):
        """
        Return blob corresponding to *pack_uri*. Raises |ValueError| if no
        matching member is present in xmlPackage.
        """
        return self._parts[str(pack_uri)]

    def close(self):
        """
        Nothing to close here
        """
        pass

    @property
    def content_types_xml(self):
        """
        Return the `[Content_Types].xml` blob from the zip package.
        """
        return self._content_type_xml

    def rels_xml_for(self, source_uri):
        """
        Return rels item XML for source with *source_uri* or None if no rels
        item is present.
        """
        try:
            rels_xml = self.blob_for(source_uri.rels_uri)
        except KeyError:
            rels_xml = None
        return rels_xml


class _ZipPkgWriter(PhysPkgWriter):
    """
    Implements |PhysPkgWriter| interface for a zip file OPC package.
    """
    def __init__(self, pkg_file):
        super(_ZipPkgWriter, self).__init__()
        self._zipf = ZipFile(pkg_file, 'w', compression=ZIP_DEFLATED)

    def close(self):
        """
        Close the zip archive, flushing any pending physical writes and
        releasing any resources it's using.
        """
        self._zipf.close()

    def write(self, pack_uri, blob):
        """
        Write *blob* to this zip package with the membername corresponding to
        *pack_uri*.
        """
        self._zipf.writestr(pack_uri.membername, blob)
